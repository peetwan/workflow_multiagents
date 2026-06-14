#!/usr/bin/env python3
"""End-to-end test for the multi-agent workflow.

Proves three things on a throwaway, generic Git repo (no project-specific
assumptions):

1. Universal: `setup` auto-detects streams from folder structure and installs
   coordination files into any repo.
2. Easy/seamless: a single `dispatch` command per task creates an isolated
   worktree + Task Card, with no long prompt.
3. Anti-collision (the point of the skill):
   - `dispatch` refuses a second task whose paths overlap an active task.
   - `guard` catches an agent that edits a file outside its allowed paths and
     flags it as a COLLISION when that file is owned by another active task.

Run:  python multi-agent-workflow/tests/test_workflow.py
Exit code 0 = all checks passed.
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


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, capture_output=True)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args])


def cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run([sys.executable, str(SCRIPT), "--repo", str(repo), *args])


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(root: Path) -> Path:
    """A generic multi-service repo: a JS frontend, a Python backend, docs."""
    repo = root / "project"
    repo.mkdir(parents=True)
    write(repo / "README.md", "# Demo project\n")
    write(repo / "frontend" / "package.json", '{"name":"frontend","version":"1.0.0"}\n')
    write(repo / "frontend" / "app.js", "console.log('hi');\n")
    write(repo / "backend" / "requirements.txt", "flask\n")
    write(repo / "backend" / "main.py", "print('backend')\n")
    write(repo / "docs" / "guide.md", "# Guide\n")
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Workflow Test")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "initial")
    git(repo, "branch", "-M", "main")
    return repo


def load_manifests(repo: Path) -> list[dict]:
    out = []
    tasks = repo / ".agents" / "tasks"
    if tasks.exists():
        for f in tasks.glob("*.json"):
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def manifest_for(repo: Path, agent: str) -> dict:
    for m in load_manifests(repo):
        if m.get("agent") == agent:
            return m
    raise AssertionError(f"no manifest for agent {agent}")


def rmtree(path: Path) -> None:
    def on_err(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=on_err)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="maw-test-"))
    try:
        print(f"Temp root: {root}")
        repo = make_repo(root)

        # --- 1. Universal setup ---------------------------------------------
        print("\n[1] Universal setup on a generic repo")
        r = cli(repo, "setup")
        check("setup exits 0", r.returncode == 0, r.stderr)
        cfg = (repo / ".agents" / "workflow-config.toml").read_text(encoding="utf-8") if (repo / ".agents" / "workflow-config.toml").exists() else ""
        check("workflow-config.toml created", bool(cfg))
        check("auto-detected 'frontend' stream", "[streams.frontend]" in cfg, cfg)
        check("auto-detected 'backend' stream", "[streams.backend]" in cfg, cfg)
        check("auto-detected 'docs' stream", "[streams.docs]" in cfg)
        for name in ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "scripts/multiagent.py", ".agents/workflow.md"]:
            check(f"installed {name}", (repo / name).exists())

        # --- 2. Easy dispatch, isolated worktrees ---------------------------
        print("\n[2] One-line dispatch per task -> isolated worktrees")
        a = cli(repo, "dispatch", "--stream", "frontend", "--task", "nav polish",
                "--agent", "claude-a", "--agent-type", "claude", "--paths", "frontend/")
        check("dispatch A (frontend) exits 0", a.returncode == 0, a.stderr)
        check("dispatch warns when workflow files are not committed to base",
              "not committed" in a.stdout, a.stdout)
        # Minimal 3-flag form: no --agent-type (inferred from the name) and no
        # --paths (defaults to the stream's). This is the seamless path.
        b = cli(repo, "dispatch", "--stream", "backend", "--task", "auth fix",
                "--agent", "codex-b")
        check("dispatch B (minimal 3-flag form) exits 0", b.returncode == 0, b.stderr)

        ma = manifest_for(repo, "claude-a")
        mb = manifest_for(repo, "codex-b")
        check("agent-type inferred from name (codex)", mb.get("agentType") == "codex", str(mb.get("agentType")))
        check("paths defaulted from stream when --paths omitted", mb.get("paths") == ["backend"], str(mb.get("paths")))
        wta = Path(ma["worktreePath"])
        wtb = Path(mb["worktreePath"])
        check("worktree A exists", wta.exists(), str(wta))
        check("worktree B exists", wtb.exists(), str(wtb))
        check("worktrees are separate dirs", wta != wtb)
        check("A Task Card written", (wta / ".agents" / "current-task.md").exists())
        check("B Task Card written", (wtb / ".agents" / "current-task.md").exists())

        # --- 3a. Collision prevented at dispatch ----------------------------
        print("\n[3a] dispatch refuses an overlapping task")
        c = cli(repo, "dispatch", "--stream", "frontend", "--task", "restyle nav",
                "--agent", "gemini-c", "--agent-type", "gemini", "--paths", "frontend/")
        check("overlapping dispatch is blocked (non-zero exit)", c.returncode != 0)
        check("conflict is explained", "conflict" in (c.stdout + c.stderr).lower(), c.stdout + c.stderr)
        check("no worktree created for blocked task", not any(m.get("agent") == "gemini-c" for m in load_manifests(repo)))

        # --- 3b. Guard catches an agent editing outside its lane ------------
        print("\n[3b] guard catches an out-of-lane edit as a COLLISION")
        # Agent A (frontend) wrongly edits a backend file owned by task B.
        (wta / "backend" / "main.py").write_text("print('A meddling in backend')\n", encoding="utf-8")
        g = cli(repo, "guard", "--id", ma["id"])
        check("guard fails when A edits backend (non-zero exit)", g.returncode != 0)
        check("guard reports COLLISION with B's path", "COLLISION" in g.stdout and "backend/main.py" in g.stdout, g.stdout)

        # Agent A reverts and stays in its lane.
        git(wta, "checkout", "--", "backend/main.py")
        (wta / "frontend" / "app.js").write_text("console.log('polished nav');\n", encoding="utf-8")
        g2 = cli(repo, "guard", "--id", ma["id"])
        check("guard passes when A stays in frontend (exit 0)", g2.returncode == 0, g2.stdout + g2.stderr)
        check("guard confirms in-scope changes", "inside allowed paths" in g2.stdout, g2.stdout)

        # --- 4. Multi-program discovery (no API; the human drives the apps) --
        print("\n[4] Each program (Claude Code / Codex / Warp) auto-finds its task")
        # Bootstrap: commit the workflow files so every new worktree carries them.
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "chore: install multi-agent workflow")
        d = cli(repo, "dispatch", "--stream", "docs", "--task", "rewrite readme", "--agent", "warp-d")
        check("dispatch D (warp, minimal form) exits 0", d.returncode == 0, d.stderr)
        check("no missing-AGENTS.md warning after bootstrap commit", "not committed" not in d.stdout, d.stdout)
        md = manifest_for(repo, "warp-d")
        check("agent-type inferred as warp", md.get("agentType") == "warp", str(md.get("agentType")))
        wtd = Path(md["worktreePath"])
        check("worktree carries AGENTS.md (Codex + Warp read this)", (wtd / "AGENTS.md").exists())
        check("worktree carries CLAUDE.md (Claude Code reads this)", (wtd / "CLAUDE.md").exists())
        check("worktree carries WARP.md (Warp also reads this)", (wtd / "WARP.md").exists())
        check("worktree has the Task Card", (wtd / ".agents" / "current-task.md").exists())
        agents_txt = (wtd / "AGENTS.md").read_text(encoding="utf-8") if (wtd / "AGENTS.md").exists() else ""
        check("AGENTS.md points every tool to the Task Card",
              ".agents/current-task.md" in agents_txt, agents_txt[:200])

        print(f"\n==== {PASSED} passed, {FAILED} failed ====")
        return 0 if FAILED == 0 else 1
    finally:
        try:
            rmtree(root)
        except OSError as exc:
            print(f"(cleanup warning: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
