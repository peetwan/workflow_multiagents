#!/usr/bin/env python3
"""Stability tests for the MCP layer: the server survives a bad repo and garbage
input, mcp-check reports OK/FAIL without crashing or hanging, per-repo servers
coexist, and mcp-config --write self-verifies.

Run:  python multi-agent-workflow/tests/test_mcp_stability.py
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


def drive(repo, lines, timeout=25):
    """Feed raw lines (already newline-terminated string) to serve-mcp; return {id: resp}."""
    proc = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "serve-mcp"],
                          input=lines, text=True, capture_output=True, timeout=timeout)
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
    return out, proc


def new_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "frontend").mkdir(exist_ok=True)
    (path / "frontend" / "package.json").write_text('{"n":"fe"}\n', encoding="utf-8")
    git(path, "init")
    git(path, "config", "user.email", "t@e.c")
    git(path, "config", "user.name", "T")
    git(path, "add", "-A")
    git(path, "commit", "-m", "init")
    git(path, "branch", "-M", "main")
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
    root = Path(tempfile.mkdtemp(prefix="maw-mcps-"))
    try:
        init_req = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        list_req = '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'

        # --- 1. serve-mcp starts even with a bad/missing repo --------------
        print("[1] serve-mcp survives a bad --repo (handshake still works)")
        bad = root / "does_not_exist"
        resps, _ = drive(bad, init_req + list_req)
        check("initialize responds despite bad repo",
              resps.get(1, {}).get("result", {}).get("serverInfo", {}).get("name") == "multiagent-workflow",
              str(resps.get(1)))
        check("tools/list still returns the tools", len(resps.get(2, {}).get("result", {}).get("tools", [])) == 6,
              str(resps.get(2)))

        # --- 2. garbage input never kills the server ----------------------
        print("\n[2] garbage input does not kill the server")
        repo = new_repo(root / "alpha")
        garbage = "this is not json\n" + "{ broken json\n" + init_req + "\n\n" + list_req
        resps, proc = drive(repo, garbage)
        check("server replied to the valid requests after garbage",
              1 in resps and 2 in resps, proc.stdout[:200])
        check("server stdout stayed pure JSON-RPC",
              all((not ln.strip()) or ln.strip().startswith("{") for ln in proc.stdout.splitlines()),
              proc.stdout[:200])

        # --- 3. mcp-config --write self-verifies + mcp-check reports OK ---
        print("\n[3] mcp-config --write verifies, mcp-check confirms OK")
        cfg = root / "cfg.json"
        w = cli(repo, "mcp-config", "--config", str(cfg), "--write")
        check("mcp-config --write runs a health check", "health check: [OK]" in w.stdout, w.stdout[-200:])
        chk = cli(repo, "mcp-check", "--config", str(cfg))
        check("mcp-check exits 0 for a working server", chk.returncode == 0, chk.stdout)
        check("mcp-check names the per-repo server and reports OK",
              "multiagent-alpha" in chk.stdout and "[OK]" in chk.stdout, chk.stdout)

        # --- 4. mcp-check reports FAIL (no crash/hang) for a broken server --
        print("\n[4] mcp-check reports a broken server as FAIL (no hang)")
        cfg2 = root / "cfg2.json"
        cfg2.write_text(json.dumps({"mcpServers": {
            "multiagent-broken": {"command": sys.executable, "args": ["-c", "pass"]}}}), encoding="utf-8")
        chk2 = cli(repo, "mcp-check", "--config", str(cfg2))
        check("mcp-check exits non-zero on a broken server", chk2.returncode != 0, chk2.stdout)
        check("mcp-check marks the broken server with [X]",
              "multiagent-broken" in chk2.stdout and "[X]" in chk2.stdout, chk2.stdout)

        # --- 5. per-repo servers coexist in one config ---------------------
        print("\n[5] two repos register two coexisting servers")
        repo_b = new_repo(root / "beta")
        cli(repo_b, "mcp-config", "--config", str(cfg), "--write")  # cfg already has alpha
        data = json.loads(cfg.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        check("both multiagent-alpha and multiagent-beta are present",
              "multiagent-alpha" in servers and "multiagent-beta" in servers, str(list(servers)))

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
