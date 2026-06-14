#!/usr/bin/env python3
"""Tests for the upgrade commands: install-hooks (real-time block), board,
radar, batch dispatch, launch, land, cleanup.

Run:  python multi-agent-workflow/tests/test_upgrade.py
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


def check(label: str, cond: bool, detail: str = "") -> None:
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


def head(repo) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def rmtree(path: Path):
    def on_err(fn, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=on_err)


def manifests(repo):
    out = {}
    for f in (repo / ".agents" / "tasks").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["agent"]] = d
    return out


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="maw-up-"))
    try:
        repo = root / "project"
        write(repo / "frontend" / "package.json", '{"n":"fe"}\n')
        write(repo / "frontend" / "app.js", "// fe\n")
        write(repo / "backend" / "requirements.txt", "flask\n")
        write(repo / "backend" / "api.py", "# be\n")
        write(repo / "config.json", "{}\n")
        git(repo, "init")
        git(repo, "config", "user.email", "t@e.c")
        git(repo, "config", "user.name", "T")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "initial")
        git(repo, "branch", "-M", "main")
        cli(repo, "init")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "bootstrap")

        # --- install-hooks --------------------------------------------------
        print("[1] install-hooks")
        ih = cli(repo, "install-hooks")
        check("install-hooks exits 0", ih.returncode == 0, ih.stderr)
        hook = repo / ".git" / "hooks" / "pre-commit"
        check("pre-commit hook written", hook.exists())
        check("hook has our marker", "multi-agent-workflow guard" in (hook.read_text(encoding="utf-8") if hook.exists() else ""))

        # --- batch dispatch -------------------------------------------------
        print("\n[2] dispatch --from (batch)")
        write(repo / "tasks.txt",
              "frontend | claude | nav polish | frontend/\n"
              "backend  | codex  | rate limit | backend/\n")
        b = cli(repo, "dispatch", "--from", str(repo / "tasks.txt"))
        check("batch dispatch exits 0", b.returncode == 0, b.stderr)
        man = manifests(repo)
        check("two tasks created from file", set(man) == {"claude", "codex"}, str(set(man)))
        wta = Path(man["claude"]["worktreePath"])
        wtb = Path(man["codex"]["worktreePath"])
        check("both worktrees exist", wta.exists() and wtb.exists())

        # --- board ----------------------------------------------------------
        print("\n[3] board")
        bd = cli(repo, "board")
        check("board exits 0 when clean", bd.returncode == 0, bd.stdout)
        check("board lists both tasks", "claude" in bd.stdout and "codex" in bd.stdout, bd.stdout)

        # --- REAL-TIME HOOK: block an out-of-lane commit --------------------
        print("\n[4] real-time hook blocks an out-of-lane commit")
        before = head(wta)
        (wta / "backend" / "api.py").write_text("# A meddling\n", encoding="utf-8")
        git(wta, "add", "backend/api.py")
        c1 = git(wta, "commit", "-m", "stray")
        check("commit is BLOCKED (non-zero exit)", c1.returncode != 0, c1.stdout + c1.stderr)
        check("HEAD did not move (no commit created)", head(wta) == before)
        check("block message explains the collision",
              "guard" in (c1.stdout + c1.stderr).lower() and "backend/api.py" in (c1.stdout + c1.stderr),
              c1.stdout + c1.stderr)
        # --no-verify bypasses
        c2 = git(wta, "commit", "--no-verify", "-m", "stray override")
        check("--no-verify bypasses the hook", c2.returncode == 0 and head(wta) != before)
        git(wta, "reset", "--hard", before)

        # in-lane commit passes the hook
        (wta / "frontend" / "app.js").write_text("// polished\n", encoding="utf-8")
        git(wta, "add", "frontend/app.js")
        c3 = git(wta, "commit", "-m", "nav")
        check("in-lane commit is allowed", c3.returncode == 0 and head(wta) != before, c3.stdout + c3.stderr)

        # --- radar: file edited by two tasks --------------------------------
        print("\n[5] radar detects a file edited by two tasks")
        (wta / "config.json").write_text('{"a":1}\n', encoding="utf-8")  # uncommitted
        (wtb / "config.json").write_text('{"b":2}\n', encoding="utf-8")  # uncommitted
        rd = cli(repo, "radar")
        check("radar flags the shared file (non-zero exit)", rd.returncode != 0, rd.stdout)
        check("radar names config.json", "config.json" in rd.stdout, rd.stdout)
        # revert so later steps are clean
        git(wta, "checkout", "--", "config.json")
        git(wtb, "checkout", "--", "config.json")

        # --- launch ---------------------------------------------------------
        print("\n[6] launch prints per-program open commands")
        lc = cli(repo, "launch")
        check("launch exits 0", lc.returncode == 0, lc.stderr)
        check("launch shows a worktree path + claude command",
              str(wta) in lc.stdout and "claude" in lc.stdout, lc.stdout)

        # --- land -----------------------------------------------------------
        print("\n[7] land prints a read-only merge plan")
        ld = cli(repo, "land")
        check("land exits 0", ld.returncode == 0, ld.stderr)
        check("land shows a merge plan with branches",
              "Merge plan" in ld.stdout and "git merge" in ld.stdout, ld.stdout)

        # --- cleanup --------------------------------------------------------
        print("\n[8] cleanup removes a closed task's worktree + branch")
        cid = man["codex"]["id"]
        cbranch = man["codex"]["branch"]
        cli(repo, "close", "--id", cid)
        cu = cli(repo, "cleanup", "--force")
        check("cleanup exits 0", cu.returncode == 0, cu.stderr)
        check("codex worktree removed", not wtb.exists())
        branches = git(repo, "branch", "--list", cbranch).stdout.strip()
        check("codex branch deleted", branches == "", branches)
        check("codex manifest removed", "codex" not in manifests(repo))

        # --- 9. Contrast: WITHOUT the hook the same stray commit lands ------
        print("\n[9] without install-hooks, the same out-of-lane commit is NOT blocked")
        repo2 = root / "nohooks"
        write(repo2 / "frontend" / "package.json", '{"n":"fe"}\n')
        write(repo2 / "frontend" / "app.js", "// fe\n")
        write(repo2 / "backend" / "requirements.txt", "flask\n")
        write(repo2 / "backend" / "api.py", "# be\n")
        git(repo2, "init")
        git(repo2, "config", "user.email", "t@e.c")
        git(repo2, "config", "user.name", "T")
        git(repo2, "add", "-A")
        git(repo2, "commit", "-m", "initial")
        git(repo2, "branch", "-M", "main")
        cli(repo2, "init")
        git(repo2, "add", "-A")
        git(repo2, "commit", "-m", "bootstrap")
        # deliberately NO install-hooks here
        cli(repo2, "dispatch", "--stream", "frontend", "--task", "nav", "--agent", "claude")
        wt2 = Path(manifests(repo2)["claude"]["worktreePath"])
        before2 = head(wt2)
        (wt2 / "backend" / "api.py").write_text("# stray\n", encoding="utf-8")
        git(wt2, "add", "backend/api.py")
        s = git(wt2, "commit", "-m", "stray")
        check("without the hook the stray commit LANDS (this is exactly what the hook prevents)",
              s.returncode == 0 and head(wt2) != before2, s.stdout + s.stderr)

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
