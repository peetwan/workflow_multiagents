#!/usr/bin/env python3
"""Tests for the MCP write actions (dispatch_task / close_task, opt-in) and the
Codex config write + check parity.

Run:  python multi-agent-workflow/tests/test_mcp_actions.py
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


def drive(repo, reqs, allow_actions=False, timeout=25):
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "serve-mcp"]
    if allow_actions:
        cmd.append("--allow-actions")
    inp = "".join(json.dumps(r) + "\n" for r in reqs)
    proc = subprocess.run(cmd, input=inp, text=True, capture_output=True, timeout=timeout)
    out = {}
    for ln in proc.stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if o.get("id") is not None:
            out[o["id"]] = o
    return out


def text(resp):
    try:
        return resp["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""


def new_repo(path: Path) -> Path:
    write(path / "frontend" / "package.json", '{"n":"fe"}\n')
    write(path / "backend" / "requirements.txt", "flask\n")
    git(path, "init")
    git(path, "config", "user.email", "t@e.c")
    git(path, "config", "user.name", "T")
    git(path, "add", "-A")
    git(path, "commit", "-m", "init")
    git(path, "branch", "-M", "main")
    cli(path, "init")
    git(path, "add", "-A")
    git(path, "commit", "-m", "bootstrap")
    return path


def rmtree(path: Path):
    def on_err(fn, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=on_err)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="maw-act-"))
    try:
        repo = new_repo(root / "project")

        # --- 1. action tools are opt-in -----------------------------------
        print("[1] write tools are off by default, on with --allow-actions")
        ro = drive(repo, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], allow_actions=False)
        ro_names = [t["name"] for t in ro.get(1, {}).get("result", {}).get("tools", [])]
        check("read-only server hides dispatch_task/close_task",
              "dispatch_task" not in ro_names and "close_task" not in ro_names, str(ro_names))
        rw = drive(repo, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], allow_actions=True)
        rw_names = [t["name"] for t in rw.get(1, {}).get("result", {}).get("tools", [])]
        check("--allow-actions exposes dispatch_task + close_task",
              "dispatch_task" in rw_names and "close_task" in rw_names, str(rw_names))

        # --- 2. dispatch_task on a read-only server is refused ------------
        print("\n[2] dispatch_task is refused on a read-only server")
        r = drive(repo, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "dispatch_task",
                                     "arguments": {"stream": "frontend", "task": "x", "agent": "a"}}}],
                  allow_actions=False)
        check("read-only dispatch_task returns 'disabled'", "disabled" in text(r.get(1, {})).lower(), text(r.get(1, {})))
        check("no task was created", not manifests(repo))

        # --- 3. dispatch_task via MCP creates a real task -----------------
        print("\n[3] dispatch_task via MCP creates an isolated worktree task")
        r = drive(repo, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "dispatch_task",
                                     "arguments": {"stream": "frontend", "task": "nav polish", "agent": "claude-desktop"}}}],
                  allow_actions=True)
        check("dispatch_task returns the handoff", "ready" in text(r.get(1, {})).lower(), text(r.get(1, {}))[:160])
        man = manifests(repo)
        check("a task manifest now exists", "claude-desktop" in man, str(list(man)))
        check("its worktree was created", "claude-desktop" in man and Path(man["claude-desktop"]["worktreePath"]).exists())

        # --- 4. close_task via MCP closes the task ------------------------
        print("\n[4] close_task via MCP marks the task closed")
        tid = man["claude-desktop"]["id"]
        r = drive(repo, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "close_task", "arguments": {"task_id": tid}}}],
                  allow_actions=True)
        check("close_task reports closed", "closed" in text(r.get(1, {})).lower(), text(r.get(1, {})))
        reloaded = json.loads((repo / ".agents" / "tasks" / f"{tid}.json").read_text(encoding="utf-8"))
        check("manifest status is now closed", reloaded.get("status") == "closed", str(reloaded.get("status")))

        # --- 5. mcp-config --actions registers --allow-actions ------------
        print("\n[5] mcp-config --actions registers a write-enabled server")
        cfg = root / "claude.json"
        cli(repo, "mcp-config", "--config", str(cfg), "--actions", "--write")
        data = json.loads(cfg.read_text(encoding="utf-8"))
        ma = next((s for n, s in data["mcpServers"].items() if n.startswith("multiagent-")), {})
        check("registered server args include --allow-actions", "--allow-actions" in ma.get("args", []), str(ma))

        # --- 6. Codex config write parity ---------------------------------
        print("\n[6] mcp-config --codex --write merges into the Codex config.toml")
        codex_cfg = root / "codex_config.toml"
        codex_cfg.write_text("[some_existing]\nkey = \"v\"\n", encoding="utf-8")
        w = cli(repo, "mcp-config", "--codex", "--write", "--codex-config", str(codex_cfg),
                "--config", str(root / "ignore.json"))
        toml_text = codex_cfg.read_text(encoding="utf-8")
        check("codex config gained the [mcp_servers.multiagent-*] block",
              "[mcp_servers.multiagent-" in toml_text, toml_text)
        check("pre-existing codex content preserved", "[some_existing]" in toml_text, toml_text)
        check("codex .bak backup written", (root / "codex_config.toml.bak").exists())
        # idempotent
        cli(repo, "mcp-config", "--codex", "--write", "--codex-config", str(codex_cfg), "--config", str(root / "ignore.json"))
        check("codex write is idempotent (one block)", codex_cfg.read_text(encoding="utf-8").count("[mcp_servers.multiagent-") == 1)

        # --- 7. mcp-check --codex verifies the Codex server ---------------
        print("\n[7] mcp-check --codex verifies the Codex-registered server")
        chk = cli(repo, "mcp-check", "--config", str(root / "none.json"), "--codex", "--codex-config", str(codex_cfg))
        check("mcp-check --codex exits 0", chk.returncode == 0, chk.stdout)
        check("it reports the codex server OK", "(codex)" in chk.stdout and "[OK]" in chk.stdout, chk.stdout)

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
