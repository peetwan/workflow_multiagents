#!/usr/bin/env python3
"""Tests for the MCP integration: the serve-mcp stdio server (so Claude Desktop /
Codex can use the workflow from a chat) and the mcp-config registration helper.

Run:  python multi-agent-workflow/tests/test_mcp.py
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "multiagent.py"
PASSED = 0
FAILED = 0


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))


def run(args, cwd=None):
    return subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, capture_output=True)


def git(repo, *a):
    return run(["git", "-C", str(repo), *a])


def cli(repo, *a):
    return run([sys.executable, str(SCRIPT), "--repo", str(repo), *a])


def write(p: Path, c: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(c, encoding="utf-8")


def manifests(repo):
    out = {}
    for f in (repo / ".agents" / "tasks").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["agent"]] = d
    return out


def drive_mcp(repo, reqs):
    """Send a list of JSON-RPC request dicts to serve-mcp; return {id: response}."""
    inp = "".join(json.dumps(r) + "\n" for r in reqs)
    proc = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "serve-mcp"],
                          input=inp, text=True, capture_output=True)
    out = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("id") is not None:
            out[o["id"]] = o
    return out, proc


def tool_text(resp):
    try:
        return resp["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""


def rmtree(path: Path):
    def on_err(fn, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=on_err)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="maw-mcp-"))
    try:
        repo = root / "project"
        write(repo / "frontend" / "package.json", '{"n":"fe"}\n')
        write(repo / "backend" / "requirements.txt", "flask\n")
        git(repo, "init")
        git(repo, "config", "user.email", "t@e.c")
        git(repo, "config", "user.name", "T")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "initial")
        git(repo, "branch", "-M", "main")
        cli(repo, "init")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "bootstrap")
        cli(repo, "dispatch", "--stream", "frontend", "--task", "nav", "--agent", "claude-desktop")
        cli(repo, "dispatch", "--stream", "backend", "--task", "api", "--agent", "codex-desktop")
        man = manifests(repo)
        ta = man["claude-desktop"]
        tb = man["codex-desktop"]

        # --- 1. MCP handshake + tools/list ---------------------------------
        print("[1] MCP handshake + tools/list")
        resps, proc = drive_mcp(repo, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        check("server's stdout is pure JSON-RPC (no stray text)", proc.stdout.strip() != "" and all(
            (not ln.strip()) or ln.strip().startswith("{") for ln in proc.stdout.splitlines()), proc.stdout[:200])
        check("initialize returns protocolVersion + serverInfo",
              resps.get(1, {}).get("result", {}).get("protocolVersion") and
              resps[1]["result"]["serverInfo"]["name"] == "multiagent-workflow", str(resps.get(1)))
        names = [t["name"] for t in resps.get(2, {}).get("result", {}).get("tools", [])]
        check("tools/list exposes the workflow tools",
              {"list_tasks", "task_card", "which_task", "board", "guard", "radar"}.issubset(set(names)), str(names))
        check("notification (no id) produced no response", 0 not in resps and None not in resps)

        # --- 2. tools/call: list_tasks, task_card, which_task --------------
        print("\n[2] tools/call returns real workflow data")
        resps, _ = drive_mcp(repo, [
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "list_tasks", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "task_card", "arguments": {"task_id": ta["id"]}}},
            {"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "which_task", "arguments": {"path": ta["worktreePath"]}}},
            {"jsonrpc": "2.0", "id": 13, "method": "tools/call", "params": {"name": "guard", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 14, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
        ])
        check("list_tasks lists both tasks", ta["id"] in tool_text(resps.get(10, {})) and tb["id"] in tool_text(resps.get(10, {})),
              tool_text(resps.get(10, {})))
        card = tool_text(resps.get(11, {}))
        check("task_card returns the card (allowed paths + stream)",
              "Allowed paths" in card and "frontend" in card, card[:160])
        check("which_task maps a folder path to its task",
              ta["id"] in tool_text(resps.get(12, {})), tool_text(resps.get(12, {}))[:160])
        check("guard runs via MCP and names the task", ta["id"] in tool_text(resps.get(13, {})),
              tool_text(resps.get(13, {}))[:160])
        check("unknown tool returns isError, not a crash", resps.get(14, {}).get("result", {}).get("isError") is True,
              str(resps.get(14)))

        # --- 3. mcp-config: print, codex, write ----------------------------
        print("\n[3] mcp-config registers the servers")
        pr = cli(repo, "mcp-config")
        check("mcp-config print has the multiagent + filesystem servers",
              "multiagent-" in pr.stdout and '"filesystem"' in pr.stdout and "serve-mcp" in pr.stdout, pr.stdout[:200])
        cx = cli(repo, "mcp-config", "--codex")
        check("mcp-config --codex prints the Codex TOML",
              "[mcp_servers.multiagent-" in cx.stdout, cx.stdout[:200])

        cfg = root / "claude_desktop_config.json"
        cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}, indent=2), encoding="utf-8")
        w = cli(repo, "mcp-config", "--config", str(cfg), "--write")
        check("mcp-config --write exits 0", w.returncode == 0, w.stderr)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        srv = data.get("mcpServers", {})
        ma_name = next((k for k in srv if k.startswith("multiagent-")), None)
        check("per-repo multiagent server registered (serve-mcp)",
              ma_name is not None and srv[ma_name].get("args", [])[-1:] == ["serve-mcp"], str(srv))
        check("filesystem server registered with both worktrees",
              str(Path(ta["worktreePath"]).resolve()) in srv.get("filesystem", {}).get("args", [])
              and str(Path(tb["worktreePath"]).resolve()) in srv.get("filesystem", {}).get("args", []), str(srv.get("filesystem")))
        check("pre-existing server preserved + backup made",
              "other" in srv and (root / "claude_desktop_config.json.bak").exists(), str(srv))

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
