#!/usr/bin/env python3
"""Tests for the one-line installers (install.sh / install.ps1). They run against
a throwaway repo using MAW_SOURCE (a local multiagent.py), so no network is
needed: download path is just curl/Invoke-WebRequest, the rest is exercised here.

Run:  python multi-agent-workflow/tests/test_installer.py
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPT = HERE.parent.parent / "scripts" / "multiagent.py"
REPO_ROOT = HERE.parent.parent.parent          # workflow_multiagents/
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"

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


def run(args, cwd=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, capture_output=True, env=e)


def git(repo, *a):
    return run(["git", "-C", str(repo), *a])


def new_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "frontend").mkdir()
    (path / "frontend" / "package.json").write_text('{"n":"fe"}\n', encoding="utf-8")
    git(path, "init")
    git(path, "config", "user.email", "t@e.c")
    git(path, "config", "user.name", "T")
    git(path, "add", "-A")
    git(path, "commit", "-m", "init")
    git(path, "branch", "-M", "main")
    return path


def assert_installed(repo: Path, out: str, label: str):
    check(f"[{label}] installer exits 0", out is not None)
    check(f"[{label}] scripts/multiagent.py was placed", (repo / "scripts" / "multiagent.py").exists())
    check(f"[{label}] AGENTS.md installed", (repo / "AGENTS.md").exists())
    committed = git(repo, "cat-file", "-e", "main:AGENTS.md").returncode == 0
    check(f"[{label}] workflow files were committed (bootstrap)", committed)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hooked = hook.exists() and "multi-agent-workflow guard" in hook.read_text(encoding="utf-8", errors="replace")
    check(f"[{label}] real-time guard hook installed", hooked)


def rmtree(path: Path):
    def on_err(fn, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=on_err)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="maw-inst-"))
    try:
        ran_any = False

        # --- install.sh via bash/sh ----------------------------------------
        sh = shutil.which("bash") or shutil.which("sh")
        if sh and INSTALL_SH.exists():
            ran_any = True
            print("[1] install.sh")
            repo = new_repo(root / "sh_repo")
            r = run([sh, str(INSTALL_SH)], cwd=repo, env={"MAW_SOURCE": str(SCRIPT)})
            if r.returncode != 0:
                check("install.sh exits 0", False, (r.stdout + r.stderr)[-300:])
            else:
                assert_installed(repo, r.stdout, "sh")
                check("[sh] prints next steps", "Installed" in r.stdout, r.stdout[-200:])
        else:
            print("[1] install.sh — skipped (no bash/sh on PATH)")

        # --- install.ps1 via PowerShell (when available) -------------------
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh and INSTALL_PS1.exists():
            ran_any = True
            print("\n[2] install.ps1")
            repo2 = new_repo(root / "ps_repo")
            r = run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1)],
                    cwd=repo2, env={"MAW_SOURCE": str(SCRIPT)})
            if r.returncode != 0:
                check("install.ps1 exits 0", False, (r.stdout + r.stderr)[-300:])
            else:
                assert_installed(repo2, r.stdout, "ps1")
        else:
            print("\n[2] install.ps1 — skipped (no PowerShell on PATH)")

        if not ran_any:
            check("at least one installer could be tested", False, "no shell available")

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
