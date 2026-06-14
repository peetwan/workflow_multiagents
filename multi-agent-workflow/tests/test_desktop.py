#!/usr/bin/env python3
"""Tests for the desktop-app flow: claude-desktop / codex-desktop agent types,
desktop-aware launch output, and the desktop-config Claude Desktop MCP helper.

Run:  python multi-agent-workflow/tests/test_desktop.py
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


def rmtree(path: Path):
    def on_err(fn, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=on_err)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="maw-desk-"))
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

        # --- 1. Desktop agent types are inferred from the name --------------
        print("[1] desktop agent types inferred from the --agent name")
        cli(repo, "dispatch", "--stream", "frontend", "--task", "nav", "--agent", "claude-desktop-a")
        cli(repo, "dispatch", "--stream", "backend", "--task", "api", "--agent", "codex-desktop-b")
        man = manifests(repo)
        check("claude-desktop-a -> claude-desktop", man["claude-desktop-a"]["agentType"] == "claude-desktop",
              man["claude-desktop-a"]["agentType"])
        check("codex-desktop-b -> codex-desktop", man["codex-desktop-b"]["agentType"] == "codex-desktop",
              man["codex-desktop-b"]["agentType"])
        wta = man["claude-desktop-a"]["worktreePath"]
        wtb = man["codex-desktop-b"]["worktreePath"]

        # --- 2. launch gives desktop-app instructions, not "cd && claude" ---
        print("\n[2] launch gives desktop-app steps")
        lc = cli(repo, "launch")
        check("launch exits 0", lc.returncode == 0, lc.stderr)
        check("Claude Desktop section points to the mcp-config setup",
              "Claude Desktop" in lc.stdout and "mcp-config" in lc.stdout, lc.stdout)
        check("Codex Desktop section mentions working directory",
              "Codex Desktop" in lc.stdout and "working directory" in lc.stdout, lc.stdout)
        check("launch shows both worktree folders",
              man["claude-desktop-a"]["id"] in lc.stdout and man["codex-desktop-b"]["id"] in lc.stdout, lc.stdout)
        check("launch does NOT tell a desktop app to run a CLI",
              "&& claude" not in lc.stdout and "&& codex" not in lc.stdout, lc.stdout)
        check("launch points to mcp-config (seamless setup)", "mcp-config" in lc.stdout, lc.stdout)

        # --- 3. desktop-config prints a valid filesystem-MCP snippet --------
        print("\n[3] desktop-config (print mode)")
        dc = cli(repo, "desktop-config")
        check("desktop-config exits 0", dc.returncode == 0, dc.stderr)
        check("snippet has the filesystem server",
              "mcpServers" in dc.stdout and "@modelcontextprotocol/server-filesystem" in dc.stdout, dc.stdout)
        check("snippet covers both worktrees",
              man["claude-desktop-a"]["id"] in dc.stdout and man["codex-desktop-b"]["id"] in dc.stdout, dc.stdout)

        # --- 4. desktop-config --write merges into an existing config -------
        print("\n[4] desktop-config --write merges, preserves other servers, backs up")
        cfg = root / "claude_desktop_config.json"
        cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x", "args": []}}}, indent=2), encoding="utf-8")
        w = cli(repo, "desktop-config", "--config", str(cfg), "--write")
        check("write exits 0", w.returncode == 0, w.stderr)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        fs = data.get("mcpServers", {}).get("filesystem", {})
        args = fs.get("args", [])
        exp_a = str(Path(wta).resolve())
        exp_b = str(Path(wtb).resolve())
        check("filesystem server added with both worktrees",
              exp_a in args and exp_b in args, str(args))
        check("pre-existing 'other' server preserved", "other" in data.get("mcpServers", {}), str(data))
        check("a .bak backup was written", (root / "claude_desktop_config.json.bak").exists())

        # --- 5. idempotent: writing again does not duplicate paths ----------
        print("\n[5] desktop-config --write is idempotent")
        cli(repo, "desktop-config", "--config", str(cfg), "--write")
        data2 = json.loads(cfg.read_text(encoding="utf-8"))
        args2 = data2["mcpServers"]["filesystem"]["args"]
        check("no duplicate worktree paths after second write",
              args2.count(exp_a) == 1 and args2.count(exp_b) == 1, str(args2))

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
