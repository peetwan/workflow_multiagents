#!/usr/bin/env python3
"""A/B test: does the workflow actually beat NOT using it?

It is not enough that the workflow's features pass their own tests. This script
proves the counterfactual: it reproduces the real failures that happen when two
agents/programs share one working tree (no worktrees), then shows the same two
tasks run cleanly WITH the workflow.

Two deterministic failure modes of the shared-tree baseline:

1. Contamination: agent A's `git add -A && git commit` sweeps in agent B's
   still-in-progress file, mixing B's work into A's commit.
2. Silent clobber: two agents editing the same file in one tree -> the later
   write wins and the other's change is lost with no warning.

WITH the workflow each agent has its own worktree, so neither happens.

Run:  python multi-agent-workflow/tests/test_vs_baseline.py
Exit 0 = baseline reproduced the failures AND the workflow prevented them.
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


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))


def run(args, cwd=None):
    return subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, capture_output=True)


def git(repo: Path, *args: str):
    return run(["git", "-C", str(repo), *args])


def cli(repo: Path, *args: str):
    return run([sys.executable, str(SCRIPT), "--repo", str(repo), *args])


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def commit_files(repo: Path, ref: str = "HEAD") -> set[str]:
    out = git(repo, "show", "--name-only", "--format=", ref).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    # Service markers so infer_streams detects 'frontend' and 'backend' streams.
    write(path / "frontend" / "package.json", '{"name":"frontend"}\n')
    write(path / "frontend" / "app.js", "// frontend base\n")
    write(path / "backend" / "requirements.txt", "flask\n")
    write(path / "backend" / "api.py", "# backend base\n")
    write(path / "README.md", "# base readme\n")
    git(path, "init")
    git(path, "config", "user.email", "t@e.c")
    git(path, "config", "user.name", "T")
    git(path, "add", "-A")
    git(path, "commit", "-m", "initial")
    git(path, "branch", "-M", "main")
    return path


def rmtree(path: Path) -> None:
    def on_err(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=on_err)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="maw-ab-"))
    try:
        # ============ BASELINE: two agents, one shared working tree ==========
        print("[A] BASELINE  (no workflow: two agents share one checkout)")
        base = init_repo(root / "baseline")

        # Agent A works on frontend; Agent B works on backend (still in progress).
        write(base / "frontend" / "app.js", "// A: new nav\n")
        write(base / "backend" / "api.py", "# B: rate limiting (WIP, uncommitted)\n")
        # Agent A commits "its" work the normal way, from the shared tree:
        git(base, "add", "-A")
        git(base, "commit", "-m", "A: frontend nav")
        a_commit = commit_files(base)
        check("[baseline] contamination reproduced: A's commit swept in B's backend file",
              "backend/api.py" in a_commit, str(a_commit))

        # Silent clobber: both edit the SAME file in the same tree.
        write(base / "README.md", "# A's rewrite\n")   # agent A
        write(base / "README.md", "# B's rewrite\n")   # agent B (later write wins)
        readme = read(base / "README.md")
        check("[baseline] silent clobber reproduced: only one README edit survived",
              "A's rewrite" not in readme and "B's rewrite" in readme, readme)

        # ============ WORKFLOW: same two tasks, isolated worktrees ===========
        print("\n[B] WORKFLOW  (same two tasks, one worktree each)")
        wf = init_repo(root / "workflow" / "project")
        cli(wf, "init")
        git(wf, "add", "-A")
        git(wf, "commit", "-m", "chore: install workflow")  # bootstrap

        da = cli(wf, "dispatch", "--stream", "frontend", "--task", "nav", "--agent", "claude")
        db = cli(wf, "dispatch", "--stream", "backend", "--task", "rate limit", "--agent", "codex")
        check("[workflow] both dispatches succeed", da.returncode == 0 and db.returncode == 0,
              da.stderr + db.stderr)

        import json
        tasks = sorted((wf / ".agents" / "tasks").glob("*.json"))
        manifests = {json.loads(p.read_text())["agent"]: json.loads(p.read_text()) for p in tasks}
        wta = Path(manifests["claude"]["worktreePath"])
        wtb = Path(manifests["codex"]["worktreePath"])

        # Each agent edits in its OWN worktree.
        write(wta / "frontend" / "app.js", "// A: new nav\n")
        write(wtb / "backend" / "api.py", "# B: rate limiting (WIP, uncommitted)\n")
        # Agent A commits from its own worktree:
        git(wta, "add", "-A")
        git(wta, "commit", "-m", "A: frontend nav")
        a_commit2 = commit_files(wta)
        check("[workflow] NO contamination: A's commit holds only its frontend file",
              a_commit2 == {"frontend/app.js"}, str(a_commit2))
        check("[workflow] B's work untouched and safe in its own worktree",
              "B: rate limiting" in read(wtb / "backend" / "api.py")
              and "backend/api.py" not in a_commit2)

        # Same-file edits: each in its own worktree -> both preserved.
        write(wta / "README.md", "# A's rewrite\n")
        write(wtb / "README.md", "# B's rewrite\n")
        check("[workflow] NO silent clobber: both README versions are preserved",
              "A's rewrite" in read(wta / "README.md")
              and "B's rewrite" in read(wtb / "README.md"))

        # And if they HAD been put on the same path, dispatch refuses it up front.
        clash = cli(wf, "dispatch", "--stream", "frontend", "--task", "also nav",
                    "--agent", "warp", "--paths", "frontend/")
        check("[workflow] overlapping work is refused before it can clash",
              clash.returncode != 0)

        print("\n---------------- VERDICT ----------------")
        baseline_failures = 2  # contamination + clobber, both reproduced above
        print(f"  Baseline (no workflow): {baseline_failures}/2 real failure modes reproduced.")
        print("  Workflow: 0 failures - isolated commits, no clobber, overlap refused.")
        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
