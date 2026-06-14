#!/usr/bin/env python3
"""Tests for the readiness flow: doctor (READY/NOT READY), ready (one-command
setup), selftest (user-runnable proof), and the space-in-path warning.

Run:  python multi-agent-workflow/tests/test_readiness.py
"""

from __future__ import annotations

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


def new_repo(path: Path) -> Path:
    write(path / "frontend" / "package.json", '{"n":"fe"}\n')
    write(path / "backend" / "requirements.txt", "flask\n")
    git(path, "init")
    git(path, "config", "user.email", "t@e.c")
    git(path, "config", "user.name", "T")
    git(path, "add", "-A")
    git(path, "commit", "-m", "initial")
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
    root = Path(tempfile.mkdtemp(prefix="maw-rdy-"))
    try:
        # --- 1. doctor on a bare repo: NOT READY (not installed) ------------
        print("[1] doctor on a bare repo -> NOT READY")
        bare = new_repo(root / "bare")
        d0 = cli(bare, "doctor")
        check("doctor exits non-zero when not installed", d0.returncode != 0, d0.stdout)
        check("doctor says NOT READY", "NOT READY" in d0.stdout, d0.stdout)
        check("doctor flags the missing install", "not fully installed" in d0.stdout, d0.stdout)

        # --- 2. installed but not committed: NOT READY (blocking) ----------
        print("\n[2] installed but not committed -> NOT READY (blocking)")
        repo = new_repo(root / "project")
        cli(repo, "init")
        d1 = cli(repo, "doctor")
        check("doctor exits non-zero before bootstrap commit", d1.returncode != 0, d1.stdout)
        check("doctor flags 'not committed'", "not committed" in d1.stdout, d1.stdout)

        # --- 3. ready --commit makes it READY ------------------------------
        print("\n[3] ready --commit -> READY")
        rdy = cli(repo, "ready", "--commit")
        check("ready --commit exits 0 (READY)", rdy.returncode == 0, rdy.stdout)
        check("ready prints READY", "READY" in rdy.stdout and "NOT READY" not in rdy.stdout, rdy.stdout)
        check("ready installed the hook", "guard hook installed" in rdy.stdout, rdy.stdout)
        # confirm with a fresh doctor
        d2 = cli(repo, "doctor")
        check("doctor now exits 0 (READY)", d2.returncode == 0, d2.stdout)
        check("workflow committed + hook installed shown",
              "committed to 'main'" in d2.stdout and "real-time guard hook installed" in d2.stdout, d2.stdout)

        # --- 4. selftest: user-runnable proof ------------------------------
        print("\n[4] selftest")
        st = run([sys.executable, str(SCRIPT), "selftest"])
        check("selftest exits 0", st.returncode == 0, st.stdout + st.stderr)
        check("selftest reports PASSED", "SELF-TEST PASSED" in st.stdout, st.stdout)
        check("selftest checks the hook block", "hook BLOCKS an out-of-lane commit" in st.stdout, st.stdout)

        # --- 5. space-in-path warning (Claude Desktop FS MCP stability) ----
        print("\n[5] desktop-config warns on worktree paths with spaces")
        spaced = new_repo(root / "a b" / "project")  # parent dir has a space
        cli(spaced, "init")
        git(spaced, "add", "-A")
        git(spaced, "commit", "-m", "bootstrap")
        cli(spaced, "dispatch", "--stream", "frontend", "--task", "nav", "--agent", "claude-desktop")
        dc = cli(spaced, "desktop-config")
        check("desktop-config warns about spaces", "spaces" in dc.stdout.lower(), dc.stdout)

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
