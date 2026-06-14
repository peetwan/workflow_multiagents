#!/usr/bin/env python3
"""Repo-local multi-agent workflow helper.

This script is dependency-free and can be run from the skill folder or copied
into a target repository by `install`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


RUNTIME_GITIGNORE = [
    ".agents/current-task.md",
    ".agents/tasks/*.json",
    ".agents/tasks/*.handoff.md",
    ".agents/locks/*.lock",
]

AGENT_TYPE_NOTES = {
    "generic": "This Task Card is the complete task contract. Do not assume any hidden chat context.",
    "codex": "Codex note: use this worktree as the active workspace, preserve user changes, and keep edits scoped.",
    "claude": "Claude note: open the exact worktree folder as the project; do not edit from the original checkout.",
    "gemini": "Gemini note: set your shell or IDE working directory to the worktree before reading or editing files.",
    "antigravity": "Antigravity note: attach/open the generated worktree as the project workspace before starting.",
    "qwen": "Qwen note: treat this Task Card as the full contract and avoid broad rewrites outside the allowed paths.",
    "warp": "Warp note: open this worktree folder in your Warp session. Warp reads AGENTS.md and the Task Card; keep edits inside the allowed paths.",
    "claude-desktop": "Claude Desktop note: this is a chat app, not a CLI. Grant it filesystem access to this worktree (claude_desktop_config.json; see `multiagent.py desktop-config`), open a NEW chat, paste the Task Card path, and edit only inside the worktree.",
    "codex-desktop": "Codex Desktop note: open a NEW project/thread whose working directory is this worktree. It pins the absolute path, so do not move the folder, and keep edits inside it (the guard hook contains any out-of-project edit).",
    "openweight": "Openweight/local note: run shell commands from the worktree and ask before destructive or unclear actions.",
}

AGENT_ENTRYPOINTS = {
    "CLAUDE.md": "Claude",
    "GEMINI.md": "Gemini",
    "ANTIGRAVITY.md": "Antigravity",
    "QWEN.md": "Qwen",
    "WARP.md": "Warp",
    "OPENWEIGHT.md": "Openweight/local agents",
}

AGENT_ENTRYPOINT_BODY = """\
# {agent_name} Multi-Agent Workflow

This repository uses a universal multi-agent workflow.

Before editing:

1. Read `AGENTS.md` if present.
2. Read `.agents/workflow.md` if present.
3. Read `.agents/quickstart.md` if you need the human workflow.
4. If `.agents/current-task.md` exists, treat it as this worktree's active Task Card.
5. Work only inside the paths allowed by the Task Card.
6. Do not edit blocked paths or another agent's worktree.
7. Run relevant checks before reporting completion.

Final report:

- changed files
- checks run
- risks/follow-ups
- whether the branch is ready for PR/merge
"""

QUICKSTART_BODY = """\
# Multi-Agent Quickstart

This project is ready for parallel AI agent work.

## Normal User Flow

Talk normally to one orchestrator agent:

```text
Set up Claude for PDFM docs, Codex for Basket UI, and Qwen for tests.
Keep Signal Bot and Luxalgo Bot untouched.
```

The orchestrator should create one Task Card, one branch, and one worktree per
agent. You do not need a long prompt.

## What To Tell Each Agent

Open the generated worktree in Codex, Claude, Gemini, Antigravity, Qwen, or any
local coding agent, then say:

```text
Please work on the current task in .agents/current-task.md.
```

That Task Card is the source of truth. The agent should stay inside the allowed
paths, run checks, and report changed files, checks, and risks.

## Useful Commands

```powershell
python scripts/multiagent.py doctor
python scripts/multiagent.py status
python scripts/multiagent.py guard
python scripts/multiagent.py examples
```

Dispatch example:

```powershell
python scripts/multiagent.py dispatch --stream docs --task "refresh PDFM docs" --agent claude-docs --agent-type claude --paths docs/
```

Close a merged task:

```powershell
python scripts/multiagent.py close --id <task-id>
```
"""


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise SystemExit(f"Command failed: {' '.join(cmd)}\n{detail}")
    return proc


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], check=check)


def repo_root(start: Path) -> Path:
    proc = run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0:
        raise SystemExit(f"Not a git repository: {start}")
    return Path(proc.stdout.strip()).resolve()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned:
        raise SystemExit(f"Cannot create slug from: {value!r}")
    return cleaned[:80]


def norm_path(value: str) -> str:
    # Strip a leading "./" prefix without eating the leading dot of dotfiles such
    # as ".github" or ".agents" (str.lstrip treats its arg as a character set).
    cleaned = value.strip().strip('"').strip("'").replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.rstrip("/")


def overlaps(left: str, right: str) -> bool:
    a = norm_path(left)
    b = norm_path(right)
    return a == b or a.startswith(f"{b}/") or b.startswith(f"{a}/")


def now_id(agent: str, task: str) -> str:
    return f"{_dt.datetime.now():%Y%m%d}-{slug(agent)}-{slug(task)}"


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    return parse_simple_toml(text)


def parse_simple_toml(text: str) -> dict[str, Any]:
    """Parse the limited TOML shape generated by this script.

    This keeps the helper usable on Python 3.8-3.10 without third-party
    dependencies. It supports top-level string/list keys and `[streams.<name>]`
    tables with string/list values.
    """

    root: dict[str, Any] = {}
    current: dict[str, Any] = root
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            parts = section.split(".")
            current = root
            for part in parts:
                current = current.setdefault(part, {})
            continue
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if value.startswith("["):
            current[key] = json.loads(value)
        else:
            current[key] = json.loads(value)
    return root


def top_level_entries(repo: Path) -> list[Path]:
    ignored = {".git", ".agents", ".github", "node_modules", "dist", "build", "__pycache__"}
    return sorted([p for p in repo.iterdir() if p.name not in ignored], key=lambda p: p.name.lower())


def detect_service_dirs(repo: Path) -> list[str]:
    markers = {
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
    }
    services: list[str] = []
    for entry in top_level_entries(repo):
        if entry.is_dir() and any((entry / marker).exists() for marker in markers):
            services.append(f"{entry.name}/")
    return services


def detect_docs(repo: Path) -> list[str]:
    docs: list[str] = []
    for name in ["docs", "doc", "wiki", "docs_th"]:
        if (repo / name).is_dir():
            docs.append(f"{name}/")
    for name in ["README.md", "CLAUDE.md", "AGENTS.md"]:
        if (repo / name).exists():
            docs.append(name)
    return docs


def infer_streams(repo: Path) -> dict[str, dict[str, Any]]:
    services = detect_service_dirs(repo)
    streams: dict[str, dict[str, Any]] = {}
    if services:
        if len(services) == 1:
            streams["app"] = {"status": "active", "paths": services, "blocked": []}
        else:
            for service in services:
                stream = slug(service.strip("/"))
                streams[stream] = {
                    "status": "active",
                    "paths": [service],
                    "blocked": [s for s in services if s != service],
                }
    else:
        source_dirs = [f"{p.name}/" for p in top_level_entries(repo) if p.is_dir()]
        streams["app"] = {"status": "active", "paths": source_dirs or ["."], "blocked": []}

    docs = detect_docs(repo)
    if docs:
        streams["docs"] = {"status": "shared", "paths": docs, "blocked": []}

    ops_paths = [p for p in [".github/", "scripts/", ".agents/"] if (repo / p.rstrip("/")).exists()]
    if (repo / "AGENTS.md").exists():
        ops_paths.append("AGENTS.md")
    streams["ops"] = {"status": "shared", "paths": sorted(set(ops_paths or [".github/", "scripts/", ".agents/"])), "blocked": []}
    return streams


def format_toml_list(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(v) for v in values) + "]"


def write_default_config(repo: Path, force: bool = False) -> Path:
    config = repo / ".agents" / "workflow-config.toml"
    if config.exists() and not force:
        return config
    streams = infer_streams(repo)
    current_branch = git(repo, "branch", "--show-current", check=False).stdout.strip()
    base = current_branch or "main"
    lines = [
        '# Generated by the "multi-agent-workflow" skill. Review before broad dispatch.',
        'task_contract_version = "1"',
        f'default_base = "{base}"',
        'worktree_root = "../_worktrees"',
        'supported_agent_types = ["generic", "codex", "claude", "gemini", "antigravity", "qwen", "warp", "openweight"]',
        "",
    ]
    for name, data in streams.items():
        lines.append(f"[streams.{name}]")
        lines.append(f'status = "{data["status"]}"')
        lines.append(f"paths = {format_toml_list(data['paths'])}")
        lines.append(f"blocked = {format_toml_list(data.get('blocked', []))}")
        lines.append("")
    config.write_text("\n".join(lines), encoding="utf-8")
    return config


def append_unique_lines(path: Path, lines: list[str]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    existing_lines = set(existing.splitlines())
    additions = [line for line in lines if line == "" or line not in existing_lines]
    if not any(line for line in additions):
        return
    while additions and additions[-1] == "":
        additions.pop()
    separator = "" if existing.endswith("\n") or not existing else "\n"
    path.write_text(existing + separator + "\n".join(additions) + "\n", encoding="utf-8")


def write_agent_entrypoints(repo: Path, force: bool = False) -> None:
    for filename, agent_name in AGENT_ENTRYPOINTS.items():
        path = repo / filename
        content = AGENT_ENTRYPOINT_BODY.format(agent_name=agent_name)
        if not path.exists() or force:
            path.write_text(content, encoding="utf-8")
            continue
        marker = "## Universal Multi-Agent Workflow"
        existing = path.read_text(encoding="utf-8", errors="replace")
        if marker not in existing:
            append_unique_lines(
                path,
                [
                    "",
                    marker,
                    "",
                    "Read `AGENTS.md`, `.agents/workflow.md`, `.agents/quickstart.md`, and `.agents/current-task.md` before editing.",
                    "Stay inside the Task Card's allowed paths and report changed files/checks/risks.",
                ],
            )


def ensure_dirs(repo: Path) -> None:
    for rel in [".agents/tasks", ".agents/locks", "scripts"]:
        (repo / rel).mkdir(parents=True, exist_ok=True)
    for rel in [".agents/tasks/.gitkeep", ".agents/locks/.gitkeep"]:
        path = repo / rel
        if not path.exists():
            path.write_text("", encoding="utf-8")


def install(repo: Path, force: bool = False, agent_files: bool = True) -> None:
    ensure_dirs(repo)
    config = write_default_config(repo, force=force)
    workflow = repo / ".agents" / "workflow.md"
    if force or not workflow.exists():
        workflow.write_text(
            textwrap.dedent(
                """\
                # Multi-Agent Workflow

                Default rule: one task = one agent = one branch = one worktree.

                This workflow is agent-neutral. Use it for Codex, Claude, Gemini,
                Antigravity, Qwen, openweight/local agents, or any other coding agent.

                Use `scripts/multiagent.py status` before starting agents.
                Use `scripts/multiagent.py dispatch --stream <stream> --task <task> --agent <name> --agent-type <type> --paths <paths...>` to create isolated work.
                In each worktree, read `.agents/current-task.md` before editing.
                Keep edits inside the Task Card's allowed paths.
                Run `scripts/multiagent.py guard` from the main checkout to confirm no agent edited outside its allowed paths.
                Close the task manifest after merge with `scripts/multiagent.py close --id <task-id>`.
                """
            ),
            encoding="utf-8",
        )
    quickstart = repo / ".agents" / "quickstart.md"
    if force or not quickstart.exists():
        quickstart.write_text(QUICKSTART_BODY, encoding="utf-8")
    readme = repo / ".agents" / "README.md"
    if force or not readme.exists():
        readme.write_text(
            "Local coordination files for multi-agent work. Runtime task manifests, Task Cards, and handoff files are ignored by git.\n",
            encoding="utf-8",
        )
    agents = repo / "AGENTS.md"
    if not agents.exists():
        agents.write_text(
            textwrap.dedent(
                """\
                # Agent Rules

                This file is the cross-tool entry point. Claude Code, Codex, and
                Warp all read `AGENTS.md` (Claude Code also reads `CLAUDE.md`), so
                the same rules apply no matter which program opens this folder.

                1. If `.agents/current-task.md` exists, it is your Task Card. Read
                   it first and work only inside its allowed paths.
                2. Otherwise read `.agents/workflow.md` and `.agents/quickstart.md`.
                3. One task = one branch = one worktree. Do not edit another
                   worktree or paths owned by another task.
                4. Before reporting done: list changed files, checks run, and risks.
                """
            ),
            encoding="utf-8",
        )
    else:
        marker = "## Multi-Agent Workflow"
        if marker not in agents.read_text(encoding="utf-8", errors="replace"):
            append_unique_lines(
                agents,
                [
                    "",
                    marker,
                    "",
                    "Read `.agents/workflow.md` and `.agents/quickstart.md`. If `.agents/current-task.md` exists, read it before editing and stay inside its allowed paths.",
                ],
            )
    append_unique_lines(repo / ".gitignore", ["", "# Multi-agent workflow runtime", *RUNTIME_GITIGNORE])
    shutil.copy2(Path(__file__).resolve(), repo / "scripts" / "multiagent.py")
    if agent_files:
        write_agent_entrypoints(repo, force=force)
    print(f"Installed universal multi-agent workflow in {repo}")
    print(f"Review config: {config}")
    if agent_files:
        print("Installed agent entry files: CLAUDE.md, GEMINI.md, ANTIGRAVITY.md, QWEN.md, OPENWEIGHT.md")
    print("Next: use natural language in any agent, e.g. 'Please work on .agents/current-task.md'.")


def inspect(repo: Path) -> None:
    branch = git(repo, "branch", "--show-current", check=False).stdout.strip() or "(detached)"
    remotes = git(repo, "remote", "-v", check=False).stdout.strip()
    status = git(repo, "status", "--short", "--branch", check=False).stdout.strip()
    worktrees = git(repo, "worktree", "list", check=False).stdout.strip()
    services = detect_service_dirs(repo)
    docs = detect_docs(repo)
    existing = [
        rel
        for rel in [
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            "ANTIGRAVITY.md",
            "QWEN.md",
            "OPENWEIGHT.md",
            ".agents/workflow-config.toml",
            ".agents/workflow.md",
            ".github/pull_request_template.md",
        ]
        if (repo / rel).exists()
    ]
    print(f"Repo: {repo}")
    print(f"Branch: {branch}")
    print("\nStatus:")
    print(status or "(clean)")
    print("\nRemotes:")
    print(remotes or "(none)")
    print("\nDetected service/app folders:")
    print("\n".join(f"- {s}" for s in services) or "- none")
    print("\nDetected docs:")
    print("\n".join(f"- {d}" for d in docs) or "- none")
    print("\nExisting coordination files:")
    print("\n".join(f"- {e}" for e in existing) or "- none")
    print("\nWorktrees:")
    print(worktrees or "(none)")
    print("\nRecommendation:")
    if not (repo / ".agents/workflow-config.toml").exists():
        print("- Run install, then review `.agents/workflow-config.toml` before dispatching agents.")
    else:
        print("- Review active task manifests with status before dispatching more work.")


def _which(name: str) -> str | None:
    return shutil.which(name)


def _committed_on_base(repo: Path, base: str, rel: str) -> bool:
    return run(["git", "-C", str(repo), "cat-file", "-e", f"{base}:{rel}"], check=False).returncode == 0


def _hook_present(repo: Path) -> bool:
    try:
        pre = _hooks_dir(repo) / "pre-commit"
        return pre.exists() and HOOK_MARKER in pre.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _config_base(repo: Path) -> str:
    cfg = repo / ".agents" / "workflow-config.toml"
    if cfg.exists():
        try:
            return load_toml(cfg).get("default_base", "main") or "main"
        except Exception:
            return "main"
    return "main"


def doctor(repo: Path) -> int:
    """Readiness check: a flutter-doctor-style checklist with a clear verdict.

    Returns 0 when the repo is READY for multi-agent work, 1 otherwise. Output is
    ASCII-only so it is stable across every terminal/encoding.
    """
    print("Multi-Agent Workflow - Readiness Check")
    print("=" * 42)
    counts = {"fatal": 0, "warn": 0}

    def ok(msg):
        print(f"  [OK] {msg}")

    def bad(msg, fix=""):
        counts["fatal"] += 1
        print(f"  [X]  {msg}")
        if fix:
            print(f"       -> {fix}")

    def rec(msg, fix=""):
        counts["warn"] += 1
        print(f"  [!]  {msg}")
        if fix:
            print(f"       -> {fix}")

    def info(msg):
        print(f"  [i]  {msg}")

    base = _config_base(repo)

    # 1. workflow installed
    missing = [r for r in [".agents/workflow-config.toml", "AGENTS.md", "scripts/multiagent.py", ".agents/workflow.md"]
               if not (repo / r).exists()]
    if missing:
        bad(f"workflow not fully installed (missing: {', '.join(missing)})", "python scripts/multiagent.py ready")
    else:
        ok("workflow installed (.agents/, AGENTS.md, scripts/multiagent.py)")

    # 2. committed to the base branch (so worktrees carry the entry files)
    if not missing:
        not_committed = [r for r in ["AGENTS.md", "CLAUDE.md", ".agents/workflow.md"]
                         if (repo / r).exists() and not _committed_on_base(repo, base, r)]
        if not_committed:
            bad(f"workflow files not committed to '{base}' (new worktrees will NOT carry them)",
                "python scripts/multiagent.py ready --commit")
        else:
            ok(f"workflow committed to '{base}' (worktrees carry AGENTS.md / CLAUDE.md)")

    # 3. runtime ignore rules
    gi = repo / ".gitignore"
    if gi.exists() and ".agents/current-task.md" in gi.read_text(encoding="utf-8", errors="replace"):
        ok("runtime files are git-ignored")
    else:
        rec("runtime ignore rules missing in .gitignore", "python scripts/multiagent.py install")

    # 4. real-time guard hook
    if _hook_present(repo):
        ok("real-time guard hook installed")
    else:
        rec("real-time guard hook NOT installed (commits are not lane-checked)",
            "python scripts/multiagent.py install-hooks")

    # 5. python for the hook
    py = _which("python") or _which("python3")
    if py:
        ok(f"python available for the hook ({Path(py).name})")
    else:
        rec("python is not on PATH (the commit hook will be skipped)", "install Python and add it to PATH")

    # 6. agent CLIs (informational)
    found = [n for n in ("claude", "codex", "gemini", "qwen") if _which(n)]
    info("agent CLIs on PATH: " + (", ".join(found) if found else "none")
         + "  (desktop apps and Warp do not need a CLI)")

    # 7. active tasks + guard/radar + space-in-path stability check
    active = active_manifests(repo)
    if active:
        owners = _owners(active)
        viol = 0
        spaces = []
        by_file: dict[str, set] = {}
        for m in active:
            wt = Path(m.get("worktreePath", ""))
            if " " in str(wt):
                spaces.append(str(wt))
            if wt.exists():
                changed = worktree_changes(wt, m.get("base", "main"))
                viol += len(_violations_for(changed, [norm_path(p) for p in m.get("paths", [])], owners, m.get("id", "")))
                for f in changed:
                    by_file.setdefault(norm_path(f), set()).add(m.get("id", ""))
        clashes = sum(1 for ids in by_file.values() if len(ids) > 1)
        msg = f"{len(active)} active task(s), {viol} guard violation(s), {clashes} radar clash(es)"
        if viol or clashes:
            rec(msg, "python scripts/multiagent.py board   (then guard / radar)")
        else:
            ok(msg)
        if spaces:
            rec(f"{len(spaces)} worktree path(s) contain spaces (Claude Desktop's filesystem MCP fails on spaces)",
                "set worktree_root to a space-free path in .agents/workflow-config.toml")
    else:
        info("no active tasks yet (run dispatch to start one)")

    # 8. Claude Desktop config (only relevant if you use Claude Desktop)
    cdc = claude_desktop_config_path()
    if cdc.exists():
        try:
            data = json.loads(cdc.read_text(encoding="utf-8"))
            cfg_args: list[str] = []
            for srv in data.get("mcpServers", {}).values():
                if isinstance(srv, dict) and isinstance(srv.get("args"), list):
                    cfg_args += [str(a) for a in srv["args"]]
            granted = sum(1 for m in active if str(Path(m.get("worktreePath", "")).resolve()) in cfg_args)
            if active and granted < len(active):
                rec(f"Claude Desktop config found, but only {granted}/{len(active)} worktree(s) granted",
                    "python scripts/multiagent.py mcp-config --write   (then restart Claude Desktop)")
            else:
                ok(f"Claude Desktop config found ({granted} worktree(s) granted)")
            if "multiagent" in data.get("mcpServers", {}):
                ok("Claude Desktop has the 'multiagent' MCP server (task-aware in chat)")
            elif active:
                rec("Claude Desktop has no 'multiagent' MCP server (cannot read tasks from a chat)",
                    "python scripts/multiagent.py mcp-config --write")
        except json.JSONDecodeError:
            rec(f"Claude Desktop config is not valid JSON ({cdc})", "fix or recreate the file")
    else:
        info(f"Claude Desktop config not found (only needed for Claude Desktop): {cdc}")

    # 9. live check: does the MCP server actually launch and respond?
    local = repo / "scripts" / "multiagent.py"
    mscript = str(local.resolve()) if local.exists() else str(Path(__file__).resolve())
    mok, mdetail = _mcp_handshake(sys.executable, [mscript, "--repo", str(repo), "serve-mcp"])
    if mok:
        ok(f"MCP server launches and responds ({mdetail})")
    else:
        rec(f"MCP server did not respond ({mdetail})", "python scripts/multiagent.py mcp-check")

    print("=" * 42)
    if counts["fatal"]:
        extra = f", {counts['warn']} recommendation(s)" if counts["warn"] else ""
        print(f"  NOT READY - {counts['fatal']} blocking issue(s){extra}.")
        print("  Fix the [X] items above, then re-run:  multiagent.py doctor")
        return 1
    if counts["warn"]:
        print(f"  READY  ({counts['warn']} recommendation(s) - see [!] above)")
    else:
        print("  READY - everything checks out.")
    print("  Prove it on this machine:   multiagent.py selftest")
    print("  Live desktop check: Claude Desktop -> type /mcp in a chat; Codex Desktop -> open the project folder.")
    return 0


def selftest() -> int:
    """Build a throwaway repo and prove the critical path works on THIS machine:
    install, isolated dispatch, and the pre-commit hook blocking an out-of-lane
    commit while allowing an in-lane one. Prints SELF-TEST PASSED/FAILED."""
    script = Path(__file__).resolve()
    root = Path(tempfile.mkdtemp(prefix="maw-selftest-"))
    steps: list[tuple[str, bool]] = []

    def step(name, cond):
        steps.append((name, bool(cond)))
        print(f"  [{'OK' if cond else 'FAIL'}] {name}")
        return bool(cond)

    try:
        repo = root / "project"
        (repo / "frontend").mkdir(parents=True)
        (repo / "backend").mkdir(parents=True)
        (repo / "frontend" / "package.json").write_text('{"n":"fe"}\n', encoding="utf-8")
        (repo / "backend" / "requirements.txt").write_text("flask\n", encoding="utf-8")

        def g(*a, cwd=repo):
            return run(["git", "-C", str(cwd), *a], check=False)

        def me(*a):
            return run([sys.executable, str(script), "--repo", str(repo), *a], check=False)

        g("init")
        g("config", "user.email", "s@t.c")
        g("config", "user.name", "S")
        g("add", "-A")
        g("commit", "-m", "init")
        g("branch", "-M", "main")

        print("Self-test on a throwaway repo (your machine):")
        step("init installs the workflow", me("init").returncode == 0 and (repo / "AGENTS.md").exists())
        g("add", "-A")
        g("commit", "-m", "bootstrap")
        step("install-hooks succeeds", me("install-hooks").returncode == 0)
        a = me("dispatch", "--stream", "frontend", "--task", "a", "--agent", "claude")
        b = me("dispatch", "--stream", "backend", "--task", "b", "--agent", "codex")
        step("dispatch creates isolated worktrees", a.returncode == 0 and b.returncode == 0)

        wt = None
        for f in (repo / ".agents" / "tasks").glob("*.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("agent") == "claude":
                wt = Path(d["worktreePath"])
        ok_wt = step("frontend worktree exists", bool(wt and wt.exists()))

        hook_blocks = hook_allows = False
        if ok_wt:
            before = g("rev-parse", "HEAD", cwd=wt).stdout.strip()
            (wt / "backend" / "api.py").write_text("# stray\n", encoding="utf-8")
            g("add", "backend/api.py", cwd=wt)
            r = g("commit", "-m", "stray", cwd=wt)
            after = g("rev-parse", "HEAD", cwd=wt).stdout.strip()
            hook_blocks = r.returncode != 0 and after == before
            g("reset", "--hard", before, cwd=wt)
            (wt / "frontend" / "app.js").write_text("// ok\n", encoding="utf-8")
            g("add", "frontend/app.js", cwd=wt)
            hook_allows = g("commit", "-m", "inlane", cwd=wt).returncode == 0
        step("hook BLOCKS an out-of-lane commit", hook_blocks)
        step("hook ALLOWS an in-lane commit", hook_allows)

        passed = all(c for _, c in steps)
        print("\n  " + ("SELF-TEST PASSED - your setup works." if passed else "SELF-TEST FAILED - see [FAIL] above."))
        if ok_wt and not hook_blocks:
            print("  (Hook step failed? Ensure `python` or `python3` is on PATH so git hooks can run it.)")
        return 0 if passed else 1
    except Exception as exc:  # noqa: BLE001 - self-test must never explode
        print(f"  SELF-TEST ERROR: {exc}")
        return 1
    finally:
        def _rm(fn, p, _e):
            try:
                os.chmod(p, stat.S_IWRITE)
                fn(p)
            except OSError:
                pass
        try:
            shutil.rmtree(root, onerror=_rm)
        except OSError:
            pass


def ready(repo: Path, do_commit: bool) -> int:
    """One command to get ready: install + hooks + (optional bootstrap commit),
    then print the readiness verdict."""
    print("Setting up the multi-agent workflow...\n")
    install(repo)
    print()
    install_hooks(repo)
    base = _config_base(repo)
    need_commit = any((repo / r).exists() and not _committed_on_base(repo, base, r)
                      for r in ["AGENTS.md", ".agents/workflow.md"])
    if need_commit:
        if do_commit:
            for r in ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "ANTIGRAVITY.md", "QWEN.md", "WARP.md",
                      "OPENWEIGHT.md", ".agents", ".gitignore", "scripts/multiagent.py"]:
                if (repo / r).exists():
                    git(repo, "add", r, check=False)
            git(repo, "commit", "-m", "chore: install multi-agent workflow", check=False)
            print("\nCommitted the workflow files so new worktrees carry them.")
        else:
            print("\nOne manual step left - commit the workflow files so worktrees carry them:")
            print("  git add AGENTS.md CLAUDE.md WARP.md .agents scripts .gitignore && git commit -m \"install multi-agent workflow\"")
            print("  (or just re-run:  multiagent.py ready --commit)")
    print()
    return doctor(repo)


def examples() -> None:
    print(
        textwrap.dedent(
            """\
            Natural-language user flow:

              "Set up this repo for parallel Codex, Claude, Gemini, and Qwen work."
              "Dispatch Claude for docs, Codex for frontend, and Qwen for tests."

            CLI equivalents:

              python scripts/multiagent.py setup
              python scripts/multiagent.py doctor
              python scripts/multiagent.py dispatch --stream docs --task "refresh docs" --agent claude-docs --agent-type claude --paths docs/
              python scripts/multiagent.py dispatch --stream frontend --task "nav polish" --agent codex-ui --agent-type codex --paths src/Nav.tsx

            After dispatch:

              Open the generated worktree in the target agent and say:
              "Please work on the current task in .agents/current-task.md."
            """
        )
    )


def task_root(repo: Path) -> Path:
    root = repo / ".agents" / "tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_manifests(repo: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in task_root(repo).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = str(path)
            items.append(data)
        except json.JSONDecodeError:
            print(f"Warning: could not read manifest {path}", file=sys.stderr)
    return items


def load_config(repo: Path) -> dict[str, Any]:
    config_path = repo / ".agents" / "workflow-config.toml"
    if not config_path.exists():
        raise SystemExit("Missing .agents/workflow-config.toml. Run install first.")
    return load_toml(config_path)


def stream_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    streams = config.get("streams", {})
    if name not in streams:
        raise SystemExit(f"Unknown stream '{name}'. Add it to .agents/workflow-config.toml first.")
    return streams[name]


def active_conflicts(repo: Path, requested: list[str], task_id: str) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    for manifest in load_manifests(repo):
        if manifest.get("id") == task_id or manifest.get("status", "active") in {"closed", "merged"}:
            continue
        for owned in manifest.get("paths", []):
            for path in requested:
                if overlaps(owned, path):
                    conflicts.append(
                        {
                            "id": manifest.get("id", ""),
                            "agent": manifest.get("agent", ""),
                            "stream": manifest.get("stream", ""),
                            "owned": owned,
                            "requested": path,
                        }
                    )
    return conflicts


def create_worktree(repo: Path, branch: str, target: Path, base: str, no_fetch: bool) -> None:
    if not no_fetch:
        git(repo, "fetch", "origin", "--prune", check=False)
    remote_ref = f"refs/remotes/origin/{base}"
    has_remote = git(repo, "show-ref", "--verify", "--quiet", remote_ref, check=False).returncode == 0
    start = f"origin/{base}" if has_remote else base
    target.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-b", branch, str(target), start)


def make_task_card(
    agent: str,
    agent_type: str,
    task: str,
    stream: str,
    branch: str,
    worktree: Path,
    paths: list[str],
    blocked: list[str],
) -> str:
    allowed = "\n".join(f"- {p}" for p in paths)
    denied = "\n".join(f"- {p}" for p in blocked) or "- none configured"
    adapter_note = AGENT_TYPE_NOTES.get(agent_type, AGENT_TYPE_NOTES["generic"])
    return textwrap.dedent(
        f"""\
        # Current Agent Task

        You are working as: {agent}
        Agent runtime: {agent_type}
        Task: {task}
        Stream: {stream}
        Branch: {branch}
        Use this worktree only:
        {worktree}

        Runtime adapter:
        {adapter_note}

        Before touching files:
        1. Read AGENTS.md if present.
        2. Read .agents/workflow.md if present.
        3. Treat this file as the source of truth for this worktree's current task.
        4. Run git status --short --branch.

        Allowed paths:
        {allowed}

        Do not touch:
        {denied}

        Workflow:
        1. Keep edits inside the allowed paths.
        2. Do not rename project/service folders unless the user explicitly asks.
        3. Do not mix refactors with bug fixes.
        4. If a shared file is required, stop and mention it before editing.
        5. Before final answer, run the relevant checks for the changed files.
        6. Do not rely on instructions from another chat/session unless they are pasted here.

        Final report must include:
        - Changed files
        - Checks run
        - Risks or follow-ups
        - Whether the branch is ready for PR/merge
        """
    )


def infer_agent_type(agent: str) -> str:
    """Guess the runtime from the agent label so --agent-type can be omitted."""
    name = (agent or "").lower()
    if "desktop" in name:
        if "codex" in name:
            return "codex-desktop"
        if "claude" in name:
            return "claude-desktop"
    for kind in ("antigravity", "openweight", "codex", "claude", "gemini", "qwen", "warp"):
        if kind in name:
            return kind
    return "generic"


def dispatch(args: argparse.Namespace, repo: Path) -> None:
    config = load_config(repo)
    stream = stream_config(config, args.stream)
    if stream.get("status") == "parked" and not args.force:
        raise SystemExit(f"Stream '{args.stream}' is parked. Use --force only if the user explicitly unparked it.")
    task_id = now_id(args.agent, args.task)
    agent_type = args.agent_type or infer_agent_type(args.agent)
    paths = [norm_path(p) for p in (args.paths or stream.get("paths", []))]
    if not paths:
        raise SystemExit("No paths configured. Pass --paths or update .agents/workflow-config.toml.")
    conflicts = active_conflicts(repo, paths, task_id)
    if conflicts and not args.force:
        print("Path ownership conflicts detected:")
        for item in conflicts:
            print(f"- {item['id']} owns {item['owned']} overlaps requested {item['requested']}")
        raise SystemExit("Use narrower --paths, close the old task, or pass --force intentionally.")
    base = args.base or config.get("default_base", "main")
    worktree_root = Path(config.get("worktree_root", "../_worktrees"))
    if not worktree_root.is_absolute():
        worktree_root = (repo / worktree_root).resolve()
    worktree = worktree_root / args.stream / task_id
    branch = f"agent/{args.stream}/{task_id}"
    create_worktree(repo, branch, worktree, base, args.no_fetch)
    task_card = make_task_card(
        args.agent,
        agent_type,
        args.task,
        args.stream,
        branch,
        worktree,
        paths,
        list(stream.get("blocked", [])),
    )
    handoff_path = task_root(repo) / f"{task_id}.handoff.md"
    manifest_path = task_root(repo) / f"{task_id}.json"
    worktree_task_path = worktree / ".agents" / "current-task.md"
    worktree_task_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(task_card, encoding="utf-8")
    worktree_task_path.write_text(task_card, encoding="utf-8")
    manifest = {
        "id": task_id,
        "status": "active",
        "stream": args.stream,
        "task": args.task,
        "agent": args.agent,
        "agentType": agent_type,
        "branch": branch,
        "base": base,
        "worktreePath": str(worktree),
        "taskCardPath": str(worktree_task_path),
        "handoffPath": str(handoff_path),
        "paths": paths,
        "createdAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    owned = ", ".join(paths) if paths else "(stream default)"
    print(f"\n[ready] {args.stream} task -> {args.agent} ({agent_type})   id: {task_id}")
    print("  1. open this folder in your agent program (Claude Code / Codex / Warp / ...):")
    print(f"       {worktree}")
    print('  2. tell it:  Work on the current task in .agents/current-task.md')
    print(f"  owns: {owned}")
    print(f"  branch: {branch}   handoff text: {handoff_path}")
    if not (worktree / "AGENTS.md").exists():
        print(
            f"  ! AGENTS.md is not committed on '{base}', so this worktree does not carry it\n"
            "    and Codex/Warp/Claude Code may not auto-find the task. Fix once: commit the\n"
            "    workflow files (git add AGENTS.md CLAUDE.md .agents scripts && git commit) so\n"
            "    future worktrees include them. For now, paste the step-2 line to the agent."
        )
    if args.print_handoff:
        print("\nOptional handoff text:\n")
        print(task_card)


def status(repo: Path) -> None:
    manifests = load_manifests(repo)
    active = [m for m in manifests if m.get("status", "active") not in {"closed", "merged"}]
    print("Active task manifests:")
    if not active:
        print("- none")
    for item in active:
        print(f"- {item.get('id')} [{item.get('stream')}] {item.get('agent')} -> {item.get('branch')}")
        for path in item.get("paths", []):
            print(f"  owns: {path}")
    print("\nGit worktrees:")
    print(git(repo, "worktree", "list", check=False).stdout.strip() or "(none)")


def print_handoff(repo: Path, task_id: str | None) -> None:
    manifests = sorted(load_manifests(repo), key=lambda m: m.get("createdAt", ""), reverse=True)
    if task_id:
        manifests = [m for m in manifests if m.get("id") == task_id]
    if not manifests:
        raise SystemExit("No matching task handoff found.")
    handoff_path = Path(manifests[0].get("handoffPath") or manifests[0].get("promptPath"))
    print(handoff_path.read_text(encoding="utf-8"))


def close(repo: Path, task_id: str, status_value: str) -> None:
    manifest_path = task_root(repo) / f"{task_id}.json"
    if not manifest_path.exists():
        raise SystemExit(f"No manifest found for {task_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = status_value
    manifest["closedAt"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Marked {task_id} as {status_value}.")


def _is_runtime_artifact(path: str) -> bool:
    """Workflow coordination files the dispatcher writes, not agent product work."""
    p = norm_path(path)
    return (
        p == ".agents/current-task.md"
        or p.startswith(".agents/tasks/")
        or p.startswith(".agents/locks/")
    )


def worktree_changes(worktree: Path, base: str) -> list[str]:
    """Files a worktree changed relative to its base branch.

    Includes committed-on-branch and uncommitted tracked changes plus untracked
    files, so it reflects everything the task actually touched. Workflow runtime
    artifacts (the Task Card and coordination state) are excluded because the
    dispatcher writes them, not the agent.
    """
    files: set[str] = set()
    diff = git(worktree, "diff", "--name-only", base, check=False)
    if diff.returncode == 0:
        files.update(line.strip() for line in diff.stdout.splitlines() if line.strip())
    others = git(worktree, "ls-files", "--others", "--exclude-standard", check=False)
    if others.returncode == 0:
        files.update(line.strip() for line in others.stdout.splitlines() if line.strip())
    return sorted(f for f in files if not _is_runtime_artifact(f))


def active_manifests(repo: Path) -> list[dict[str, Any]]:
    return [m for m in load_manifests(repo) if m.get("status", "active") not in {"closed", "merged"}]


def _owners(active: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    owners: list[tuple[str, str, str]] = []
    for m in active:
        for p in m.get("paths", []):
            owners.append((norm_path(p), m.get("id", ""), m.get("agent", "")))
    return owners


def _violations_for(changed, allowed, owners, task_id):
    """Return [(kind, file, owner_label)] for files outside allowed paths."""
    out = []
    for f in changed:
        nf = norm_path(f)
        if any(overlaps(nf, a) for a in allowed):
            continue
        collide = next((o for o in owners if o[1] != task_id and overlaps(nf, o[0])), None)
        if collide:
            out.append(("COLLISION", f, f"{collide[1]} ({collide[2]})"))
        else:
            out.append(("OUT-OF-SCOPE", f, ""))
    return out


def main_checkout(start: Path) -> Path:
    """Resolve the main working tree from anywhere, including inside a worktree."""
    proc = run(["git", "-C", str(start), "rev-parse", "--git-common-dir"], check=False)
    common = proc.stdout.strip()
    if not common:
        return repo_root(start)
    cp = Path(common)
    if not cp.is_absolute():
        cp = (Path(start) / common).resolve()
    return cp.parent.resolve()


def _same_path(a, b) -> bool:
    try:
        ra, rb = Path(a).resolve(), Path(b).resolve()
    except OSError:
        ra, rb = Path(a), Path(b)
    return os.path.normcase(str(ra)) == os.path.normcase(str(rb))


def staged_files(worktree: Path) -> list[str]:
    proc = git(worktree, "diff", "--cached", "--name-only", check=False)
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return [f for f in files if not _is_runtime_artifact(f)]


def guard(repo: Path, task_id: str | None) -> None:
    """Verify each active task only changed files inside its allowed paths.

    This is the anti-collision check. Even if an agent ignores its Task Card,
    any edit outside its allowed paths is reported, and any edit that lands on a
    path owned by another active task is flagged as a COLLISION. Run it from the
    main checkout. Exits non-zero when any violation is found.
    """
    active = active_manifests(repo)
    if task_id:
        targets = [m for m in active if m.get("id") == task_id]
        if not targets:
            raise SystemExit(f"No active task manifest for id '{task_id}'.")
    else:
        targets = active

    if not targets:
        print("No active tasks to guard.")
        return

    owners = _owners(active)
    violations = 0
    for m in targets:
        task = m.get("id", "")
        worktree = Path(m.get("worktreePath", ""))
        allowed = [norm_path(p) for p in m.get("paths", [])]
        base = m.get("base", "main")
        print(f"\n== {task} [{m.get('stream')}] {m.get('agent')}")
        if not worktree.exists():
            print(f"  ! worktree missing: {worktree}")
            continue
        changed = worktree_changes(worktree, base)
        if not changed:
            print("  clean: no changes vs base")
            continue
        bad = _violations_for(changed, allowed, owners, task)
        if bad:
            violations += len(bad)
            print(f"  {len(changed)} changed file(s), {len(bad)} violation(s):")
            for kind, f, owner in bad:
                print(f"  {kind:<12} {f}" + (f"  -> owned by {owner}" if owner else "  (outside allowed paths)"))
        else:
            print(f"  OK: all {len(changed)} changed file(s) inside allowed paths")

    if violations:
        raise SystemExit(
            f"\nGuard failed: {violations} path violation(s). "
            "Move the work into the owning task's worktree before merge."
        )
    print("\nGuard passed: every task stayed inside its allowed paths.")


def guard_staged(start: Path) -> None:
    """Pre-commit guard: block staged changes outside the current worktree's lane.

    Exits 3 on a real violation so a hook can fail-open on any other error.
    Passes silently when the commit is not inside a known task worktree.
    """
    wt = repo_root(start)
    main = main_checkout(start)
    active = active_manifests(main)
    me = next((m for m in active if _same_path(m.get("worktreePath", ""), wt)), None)
    if me is None:
        return
    allowed = [norm_path(p) for p in me.get("paths", [])]
    bad = _violations_for(staged_files(wt), allowed, _owners(active), me.get("id", ""))
    if not bad:
        return
    print(f"multi-agent guard: commit blocked for task {me.get('id')} [{me.get('stream')}]")
    for kind, f, owner in bad:
        print(f"  {kind:<12} {f}" + (f"  -> owned by {owner}" if owner else ""))
    print("  Move these into the owning task's worktree, or override with: git commit --no-verify")
    raise SystemExit(3)


HOOK_MARKER = "# >>> multi-agent-workflow guard >>>"


def _hooks_dir(repo: Path) -> Path:
    hp = git(repo, "config", "--get", "core.hooksPath", check=False).stdout.strip()
    if hp:
        p = Path(hp)
        return p if p.is_absolute() else (repo / hp).resolve()
    common = run(["git", "-C", str(repo), "rev-parse", "--git-common-dir"], check=False).stdout.strip() or ".git"
    cp = Path(common)
    if not cp.is_absolute():
        cp = (repo / common).resolve()
    return cp / "hooks"


def install_hooks(repo: Path) -> None:
    main = main_checkout(repo)
    script = (main / "scripts" / "multiagent.py").resolve()
    if not script.exists():
        script = Path(__file__).resolve()
    hooks = _hooks_dir(main)
    hooks.mkdir(parents=True, exist_ok=True)
    pre = hooks / "pre-commit"
    chain = ""
    if pre.exists():
        existing = pre.read_text(encoding="utf-8", errors="replace")
        if HOOK_MARKER not in existing:
            backup = hooks / "pre-commit.local"
            if not backup.exists():
                shutil.copy2(pre, backup)
                try:
                    os.chmod(backup, 0o755)
                except OSError:
                    pass
            chain = '[ -x "$DIR/pre-commit.local" ] && "$DIR/pre-commit.local" "$@" || true\n'
    body = (
        "#!/bin/sh\n"
        f"{HOOK_MARKER}\n"
        "# Auto-installed by multi-agent-workflow. Blocks commits that stray outside a task lane.\n"
        'DIR="$(dirname "$0")"\n'
        f"{chain}"
        'PY="$(command -v python 2>/dev/null || command -v python3 2>/dev/null)"\n'
        '[ -n "$PY" ] || exit 0\n'
        f'SCRIPT="{script.as_posix()}"\n'
        '[ -f "$SCRIPT" ] || exit 0\n'
        '"$PY" "$SCRIPT" --repo "." guard --staged\n'
        "rc=$?\n"
        '[ "$rc" -eq 3 ] && { echo "(commit blocked by multi-agent guard; use --no-verify to override)"; exit 1; }\n'
        "exit 0\n"
        "# <<< multi-agent-workflow guard <<<\n"
    )
    pre.write_text(body, encoding="utf-8")
    try:
        os.chmod(pre, 0o755)
    except OSError:
        pass
    print(f"Installed pre-commit guard hook: {pre}")
    if chain:
        print("Chained your existing pre-commit (saved as pre-commit.local).")
    print("Every worktree commit now runs guard --staged. Override a block with: git commit --no-verify")


def cleanup(repo: Path, task_id: str | None, force: bool) -> None:
    manifests = load_manifests(repo)
    if task_id:
        targets = [m for m in manifests if m.get("id") == task_id]
        if not targets:
            raise SystemExit(f"No manifest for id '{task_id}'.")
    else:
        targets = [m for m in manifests if m.get("status") in {"closed", "merged"}]
    if not targets:
        print("Nothing to clean up. Close a finished task first: multiagent.py close --id <id>")
        return
    for m in targets:
        wt = Path(m.get("worktreePath", ""))
        branch = m.get("branch", "")
        tid = m.get("id", "")
        print(f"\n== {tid} [{m.get('stream')}] {m.get('agent')}")
        if wt.exists():
            dirty = git(wt, "status", "--porcelain", check=False).stdout.strip()
            if dirty and not force:
                print(f"  ! worktree is dirty, skipping (use --force): {wt}")
                continue
            r = git(repo, "worktree", "remove", *(["--force"] if force else []), str(wt), check=False)
            print("  removed worktree" if r.returncode == 0 else f"  ! worktree remove failed: {r.stderr.strip()}")
        else:
            git(repo, "worktree", "prune", check=False)
            print("  worktree already gone (pruned)")
        if branch:
            r = git(repo, "branch", "-D" if force else "-d", branch, check=False)
            print(f"  deleted branch {branch}" if r.returncode == 0
                  else f"  ! branch kept ({r.stderr.strip() or 'not merged; use --force'})")
        mp = task_root(repo) / f"{tid}.json"
        if mp.exists():
            mp.unlink()
            print("  removed manifest")
    print("\nCleanup done.")


def _ahead_behind(worktree: Path, base: str) -> tuple[int, int]:
    r = git(worktree, "rev-list", "--left-right", "--count", f"{base}...HEAD", check=False)
    parts = r.stdout.split()
    if r.returncode == 0 and len(parts) == 2:
        try:
            return int(parts[1]), int(parts[0])  # (ahead, behind)
        except ValueError:
            return 0, 0
    return 0, 0


def _render_board(repo: Path) -> tuple[str, int]:
    active = active_manifests(repo)
    owners = _owners(active)
    lines = [f"{'TASK':<34} {'STREAM':<14} {'AGENT':<10} {'STATE':<16} GUARD", "-" * 86]
    total = 0
    if not active:
        lines.append("(no active tasks)")
    for m in active:
        wt = Path(m.get("worktreePath", ""))
        tid = (m.get("id", "") or "")[:33]
        stream = (m.get("stream", "") or "")[:13]
        agent = (m.get("agent", "") or "")[:9]
        if not wt.exists():
            state, gtxt = "missing", "-"
        else:
            dirty = [l for l in git(wt, "status", "--porcelain", check=False).stdout.splitlines() if l.strip()]
            ahead, behind = _ahead_behind(wt, m.get("base", "main"))
            bits = []
            if dirty:
                bits.append(f"{len(dirty)} dirty")
            if ahead:
                bits.append(f"+{ahead}")
            if behind:
                bits.append(f"-{behind}")
            state = ", ".join(bits) if bits else "clean"
            allowed = [norm_path(p) for p in m.get("paths", [])]
            v = _violations_for(worktree_changes(wt, m.get("base", "main")), allowed, owners, tid)
            total += len(v)
            gtxt = "ok" if not v else f"{len(v)} VIOLATION"
        lines.append(f"{tid:<34} {stream:<14} {agent:<10} {state[:16]:<16} {gtxt}")
    lines.append("")
    lines.append(f"{len(active)} active task(s), {total} guard violation(s).")
    return "\n".join(lines), total


def board(repo: Path, once: bool = True) -> int:
    if once:
        text, viol = _render_board(repo)
        print(text)
        return 1 if viol else 0
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            text, _ = _render_board(repo)
            print(text)
            print("\n(board --watch; Ctrl-C to exit)")
            time.sleep(2)
    except KeyboardInterrupt:
        return 0


def radar(repo: Path) -> None:
    active = active_manifests(repo)
    by_file: dict[str, list[tuple[str, str]]] = {}
    for m in active:
        wt = Path(m.get("worktreePath", ""))
        if not wt.exists():
            continue
        for f in worktree_changes(wt, m.get("base", "main")):
            by_file.setdefault(norm_path(f), []).append((m.get("id", ""), m.get("agent", "")))
    clashes = {f: ow for f, ow in by_file.items() if len({o[0] for o in ow}) > 1}
    if not clashes:
        print("Radar: no file is edited by more than one active task. Safe to merge in any order.")
        return
    print("Radar: files edited by MORE THAN ONE active task (these WILL conflict at merge):")
    for f, ow in sorted(clashes.items()):
        print(f"  {f}  <- " + ", ".join(f"{i} ({a})" for i, a in ow))
    raise SystemExit(2)


def launch(repo: Path, task_id: str | None, do_open: bool) -> None:
    active = active_manifests(repo)
    if task_id:
        active = [m for m in active if m.get("id") == task_id]
        if not active:
            raise SystemExit(f"No active task for id '{task_id}'.")
    if not active:
        print("No active tasks.")
        return
    cli_cmd = {"claude": "claude", "codex": "codex", "gemini": "gemini", "qwen": "qwen"}
    say = "Work on the current task in .agents/current-task.md"
    for m in active:
        wt = m.get("worktreePath", "")
        at = m.get("agentType", "generic")
        print(f"\n[{m.get('id')}] {m.get('stream')} -> {m.get('agent')} ({at})")
        if at == "claude-desktop":
            print("  Claude Desktop (chat app, not a terminal):")
            print("    1. one-time:  multiagent.py mcp-config --write   (grants file access + task tools)")
            print("    2. in a NEW chat, say:")
            print(f"         {say}   (worktree: {wt})")
            print("       or just ask:  'what should I work on in this worktree?'")
        elif at == "codex-desktop":
            print("  Codex Desktop (chat app, not a terminal):")
            print("    1. New project/thread -> set its working directory to:")
            print(f"         {wt}")
            print(f"    2. then say:  {say}")
            print("       optional task tools:  multiagent.py mcp-config --codex  (add to ~/.codex/config.toml)")
        elif at in cli_cmd:
            print(f'  cd "{wt}" && {cli_cmd[at]}')
            print(f"  then say: {say}")
        elif at == "warp":
            print(f"  open a new Warp tab in:  {wt}")
            print(f"  then say: {say}")
        else:
            print(f'  cd "{wt}"   # then start your agent here')
            print(f"  then say: {say}")
        if do_open:
            opener = "explorer" if os.name == "nt" else ("open" if sys.platform == "darwin" else "xdg-open")
            run([opener, wt], check=False)
    if any(m.get("agentType") in {"claude-desktop", "codex-desktop"} for m in active):
        print("\nSeamless: run `multiagent.py mcp-config --write` once. Then in Claude Desktop you can")
        print("ask 'what are my multi-agent tasks?' and it reads them directly (no copy-paste).")
    if do_open:
        print("\nOpened each worktree folder in your file manager.")


def claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _write_codex_server(target: Path, name: str, command: str, args: list) -> tuple[bool, str]:
    """Append a [mcp_servers.<name>] block to a Codex config.toml. Append-only and
    idempotent: if the block is already there it is left unchanged (we never
    rewrite existing TOML, to stay safe)."""
    block = (f"[mcp_servers.{name}]\n"
             f"command = {json.dumps(command)}\n"
             f"args = {json.dumps(args)}\n")
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if f"[mcp_servers.{name}]" in existing:
        return False, "already present (left unchanged)"
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    target.parent.mkdir(parents=True, exist_ok=True)
    body = (existing.rstrip() + "\n\n" + block) if existing.strip() else block
    target.write_text(body, encoding="utf-8")
    return True, str(target)


def desktop_config(repo: Path, config_path: str | None, write: bool, server_name: str = "filesystem") -> None:
    """Emit (or merge) a Claude Desktop filesystem-MCP config that grants the app
    access to every active worktree, so a desktop agent can edit them. Prints the
    snippet by default; --write merges it into the target config file (backup kept)."""
    dirs: list[str] = []
    for m in active_manifests(repo):
        wt = m.get("worktreePath", "")
        if wt and Path(wt).exists():
            rp = str(Path(wt).resolve())
            if rp not in dirs:
                dirs.append(rp)
    if not dirs:
        print("No active worktrees to expose. Dispatch some tasks first.")
        return
    spaced = [d for d in dirs if " " in d]
    if spaced:
        print("Warning: these worktree paths contain spaces, which Claude Desktop's")
        print("filesystem MCP server cannot handle. Use a space-free worktree_root:")
        for d in spaced:
            print(f"  {d}")
        print()
    server = {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", *dirs]}
    target = Path(config_path) if config_path else claude_desktop_config_path()
    if not write:
        print("Add this 'filesystem' server to your Claude Desktop config so it can")
        print("reach every worktree, then restart Claude Desktop:\n")
        print(json.dumps({"mcpServers": {server_name: server}}, indent=2))
        print(f"\nConfig file (this OS): {target}")
        print("Or merge automatically with:  multiagent.py desktop-config --write")
        return
    data: dict[str, Any] = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"Existing config is not valid JSON: {target}")
        backup = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup)
        print(f"Backed up existing config to {backup}")
    servers = data.setdefault("mcpServers", {})
    existing = servers.get(server_name)
    if isinstance(existing, dict) and isinstance(existing.get("args"), list):
        for d in dirs:
            if d not in existing["args"]:
                existing["args"].append(d)
    else:
        servers[server_name] = server
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Granted Claude Desktop filesystem access to {len(dirs)} worktree(s) in {target}.")
    print("Restart Claude Desktop for it to take effect.")


def _path_under(child, parent) -> bool:
    try:
        c = str(Path(child).resolve())
        p = str(Path(parent).resolve())
    except OSError:
        c, p = str(child), str(parent)
    c = os.path.normcase(c)
    p = os.path.normcase(p)
    return bool(p) and (c == p or c.startswith(p + os.sep))


MCP_TOOLS = [
    {"name": "list_tasks", "description": "List active multi-agent tasks (id, stream, agent, worktree, branch).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "task_card", "description": "Get the Task Card (what to do + allowed paths) for a task id, or the newest task if no id is given.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
    {"name": "which_task", "description": "Given a folder path, return which task owns that worktree and its Task Card.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "board", "description": "One-screen status of every active task (dirty/ahead/behind + guard state).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "guard", "description": "Check that tasks only changed files inside their allowed paths (anti-collision).",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
    {"name": "radar", "description": "List files edited by more than one active task (merge-conflict risk).",
     "inputSchema": {"type": "object", "properties": {}}},
]

# Write actions are opt-in (serve-mcp --allow-actions) so a read-only server is
# the safe default.
MCP_ACTION_TOOLS = [
    {"name": "dispatch_task",
     "description": "Create an isolated worktree + branch + Task Card for a new agent task. Returns the handoff (which folder to open).",
     "inputSchema": {"type": "object", "properties": {
         "stream": {"type": "string", "description": "stream/area, e.g. frontend, backend, docs"},
         "task": {"type": "string", "description": "short task description"},
         "agent": {"type": "string", "description": "agent label, e.g. claude-desktop, codex-desktop"},
         "paths": {"type": "array", "items": {"type": "string"},
                   "description": "files or folders this task may edit (optional; defaults to the stream's)"}},
      "required": ["stream", "task", "agent"]}},
    {"name": "close_task",
     "description": "Mark a task closed (releases its path ownership). Does NOT delete the worktree.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
]


def serve_mcp(repo: Path, allow_actions: bool = False) -> None:
    """A minimal, dependency-free MCP server (stdio, newline-delimited JSON-RPC).

    Lets MCP clients (Claude Desktop, Codex) use the workflow from a chat: list
    tasks, read a Task Card, run guard/radar/board. Tool bodies shell out to this
    same CLI in a subprocess, so the server's own stdout stays pure JSON-RPC (a
    hard requirement of the MCP stdio transport).
    """
    # stdio hardening: force UTF-8 and never translate \n -> \r\n on Windows
    # (the client frames each message on a single \n; stray bytes break it).
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="")
    except (AttributeError, ValueError, OSError):
        pass
    script = Path(__file__).resolve()

    def reply(mid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def run_cmd(*args):
        proc = run([sys.executable, str(script), "--repo", str(repo), *args], check=False)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        return (out + ("\n" + err if err else "")).strip() or "(no output)"

    def card_for(m):
        head = (f"Task: {m.get('id')}  [{m.get('stream')}]  agent={m.get('agent')} ({m.get('agentType', 'generic')})\n"
                f"Worktree: {m.get('worktreePath')}\n"
                f"Allowed paths: {', '.join(m.get('paths', [])) or '(stream default)'}\n\n")
        for key in ("taskCardPath", "handoffPath"):
            val = m.get(key)
            if val and Path(val).exists():
                return head + Path(val).read_text(encoding="utf-8")
        return head + "(Task Card file not found; work only inside the allowed paths above.)"

    def call_tool(name, a):
        if name == "list_tasks":
            return run_cmd("status")
        if name == "board":
            return run_cmd("board")
        if name == "radar":
            return run_cmd("radar")
        if name == "guard":
            tid = a.get("task_id")
            return run_cmd("guard", *(["--id", tid] if tid else []))
        if name == "task_card":
            ms = active_manifests(repo)
            tid = a.get("task_id")
            m = (next((x for x in ms if x.get("id") == tid), None) if tid
                 else (sorted(ms, key=lambda x: x.get("createdAt", ""))[-1] if ms else None))
            return card_for(m) if m else "No matching active task. Use list_tasks."
        if name == "which_task":
            p = a.get("path", "")
            m = next((x for x in active_manifests(repo) if _path_under(p, x.get("worktreePath", ""))), None)
            return card_for(m) if m else f"No active task owns '{p}'. Use list_tasks to see tasks."
        if name == "dispatch_task":
            if not allow_actions:
                return "dispatch_task is disabled (read-only server). Enable with: mcp-config --actions --write"
            stream, task, agent = a.get("stream"), a.get("task"), a.get("agent")
            if not (stream and task and agent):
                return "dispatch_task needs stream, task, and agent."
            extra = (["--paths", *[str(p) for p in a["paths"]]] if a.get("paths") else [])
            return run_cmd("dispatch", "--stream", str(stream), "--task", str(task), "--agent", str(agent), *extra)
        if name == "close_task":
            if not allow_actions:
                return "close_task is disabled (read-only server). Enable with: mcp-config --actions --write"
            tid = a.get("task_id")
            return run_cmd("close", "--id", str(tid)) if tid else "close_task needs task_id."
        raise ValueError(f"unknown tool: {name}")

    for raw in sys.stdin:
        try:
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = req.get("id")
            method = req.get("method")
            if method == "initialize":
                reply(mid, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                            "serverInfo": {"name": "multiagent-workflow", "version": "1"}})
            elif method == "tools/list":
                reply(mid, {"tools": MCP_TOOLS + (MCP_ACTION_TOOLS if allow_actions else [])})
            elif method == "tools/call":
                params = req.get("params", {}) or {}
                try:
                    text = call_tool(params.get("name"), params.get("arguments", {}) or {})
                    reply(mid, {"content": [{"type": "text", "text": text}]})
                except Exception as exc:  # noqa: BLE001 - report tool errors, never crash
                    reply(mid, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
            elif method == "ping":
                reply(mid, {})
            elif mid is not None:
                reply(mid, error={"code": -32601, "message": f"method not found: {method}"})
            # notifications (no id) get no response
        except Exception:  # noqa: BLE001 - one bad message must never kill the server
            continue


def mcp_config(repo: Path, config_path: str | None, write: bool, codex: bool,
               actions: bool = False, codex_config: str | None = None) -> None:
    """Register the workflow with MCP clients so desktop apps use it from a chat:
    a shared 'filesystem' server (worktree file access) and a per-repo
    'multiagent-<repo>' server (task-awareness, so several repos coexist). Prints
    the Claude Desktop JSON, or --write merges AND verifies it; --codex prints
    (and with --write merges) the Codex config.toml block; --actions also enables
    the dispatch_task/close_task write tools."""
    repo = Path(repo).resolve()
    dirs: list[str] = []
    for m in active_manifests(repo):
        wt = m.get("worktreePath", "")
        if wt and Path(wt).exists():
            rp = str(Path(wt).resolve())
            if rp not in dirs:
                dirs.append(rp)
    repo_name = re.sub(r"[^a-z0-9]+", "-", repo.name.lower()).strip("-") or "repo"
    server_name = f"multiagent-{repo_name}"
    local = repo / "scripts" / "multiagent.py"
    # Prefer the repo-local copy: it travels with the project and stays valid
    # across reboots even if the skill source moves.
    script = str(local.resolve()) if local.exists() else str(Path(__file__).resolve())
    ma_args = [script, "--repo", str(repo), "serve-mcp"] + (["--allow-actions"] if actions else [])
    ma_server = {"command": sys.executable, "args": ma_args}
    fs_server = {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", *dirs]}

    spaced = [d for d in dirs if " " in d]
    if spaced:
        print("Warning: worktree paths contain spaces, which the filesystem MCP server cannot handle:")
        for d in spaced:
            print(f"  {d}")
        print()

    if codex:
        ctarget = Path(codex_config) if codex_config else codex_config_path()
        print("# Codex: add to ~/.codex/config.toml (Codex supports stdio MCP servers):\n")
        print(f"[mcp_servers.{server_name}]")
        print(f"command = {json.dumps(sys.executable)}")
        print(f"args = {json.dumps(ma_args)}")
        print()
        if write:
            changed, detail = _write_codex_server(ctarget, server_name, sys.executable, ma_args)
            print(f"Codex config: {('wrote ' + detail) if changed else (server_name + ' ' + detail)}")
            cok, cdetail = _mcp_handshake(sys.executable, ma_args)
            print(f"  health check: [{'OK' if cok else 'FAILED'}] {cdetail}\n")

    target = Path(config_path) if config_path else claude_desktop_config_path()
    new_servers = {server_name: ma_server}
    if dirs:
        new_servers["filesystem"] = fs_server

    if not write:
        print("Add these servers to your Claude Desktop config, then restart Claude Desktop:\n")
        print(json.dumps({"mcpServers": new_servers}, indent=2))
        print(f"\nConfig file (this OS): {target}")
        print("Or merge + verify automatically with:  multiagent.py mcp-config --write")
        return

    data: dict[str, Any] = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"Existing config is not valid JSON: {target}")
        backup = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup)
        print(f"Backed up existing config to {backup}")
    servers = data.setdefault("mcpServers", {})
    if dirs:
        fs = servers.get("filesystem")
        if isinstance(fs, dict) and isinstance(fs.get("args"), list):
            for d in dirs:
                if d not in fs["args"]:
                    fs["args"].append(d)
        else:
            servers["filesystem"] = fs_server
    servers[server_name] = ma_server
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Registered '{server_name}'" + (f" + filesystem ({len(dirs)} worktree(s))" if dirs else "") + f" in {target}.")
    ok, detail = _mcp_handshake(sys.executable, ma_args)
    print(f"  health check: [{'OK' if ok else 'FAILED'}] {detail}")
    if ok:
        print("Restart Claude Desktop, then in a chat ask: \"what are my multi-agent tasks?\"")
    else:
        print("The server did not respond - fix the above and re-run: multiagent.py mcp-config --write")


def _mcp_handshake(command, args, timeout=20):
    """Spawn an MCP stdio server and do initialize + tools/list. Returns
    (ok, detail). Uses a timeout so a hung server is reported, not waited on."""
    reqs = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
    try:
        proc = subprocess.run([command, *[str(a) for a in args]], input=reqs, text=True,
                              capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return False, f"command not found: {command}"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s (no response)"
    except OSError as exc:
        return False, f"could not start: {exc}"
    name = None
    tools = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            return False, "server wrote non-JSON to stdout (stdout pollution)"
        if o.get("id") == 1:
            name = o.get("result", {}).get("serverInfo", {}).get("name")
        elif o.get("id") == 2:
            tools = o.get("result", {}).get("tools")
    if name and tools is not None:
        return True, f"{name}, {len(tools)} tools"
    err = (proc.stderr or "").strip().splitlines()
    return False, f"no handshake (exit {proc.returncode})" + (f"; {err[-1][:120]}" if err else "")


def mcp_check(repo: Path, config_path: str | None, name: str | None,
              codex: bool = False, codex_config: str | None = None) -> int:
    """Live health check: spawn the registered MCP server(s) and confirm they
    respond. Run it anytime (e.g. after a reboot or app restart). Checks Claude
    Desktop by default; --codex also checks the Codex config.toml. Returns 0 when
    every checked server responds."""
    print("MCP health check")
    print("=" * 32)
    stats = {"total": 0, "failed": 0}

    def check_items(items, source):
        for n, s in items:
            stats["total"] += 1
            if not isinstance(s, dict) or not s.get("command"):
                print(f"  [X] {n} ({source}): malformed entry")
                stats["failed"] += 1
                continue
            ok, detail = _mcp_handshake(s["command"], s.get("args", []))
            print(f"  [{'OK' if ok else 'X'}] {n} ({source}) -> {detail}")
            if not ok:
                stats["failed"] += 1

    target = Path(config_path) if config_path else claude_desktop_config_path()
    cd_servers = {}
    if target.exists():
        try:
            cd_servers = json.loads(target.read_text(encoding="utf-8")).get("mcpServers", {})
        except json.JSONDecodeError:
            print(f"  [X] Claude Desktop config is not valid JSON: {target}")
            stats["failed"] += 1
    if name:
        check_items([(name, cd_servers[name])] if name in cd_servers else [], "claude")
    else:
        check_items([(n, s) for n, s in cd_servers.items() if str(n).startswith("multiagent")], "claude")

    if codex:
        ctarget = Path(codex_config) if codex_config else codex_config_path()
        if ctarget.exists():
            try:
                cx = load_toml(ctarget).get("mcp_servers", {})
            except Exception:  # noqa: BLE001 - a malformed codex config must not crash the check
                cx = {}
            check_items([(n, s) for n, s in cx.items() if str(n).startswith("multiagent")], "codex")
        else:
            print(f"  [i] Codex config not found: {ctarget}")

    if stats["total"] == 0:
        local = repo / "scripts" / "multiagent.py"
        script = str(local.resolve()) if local.exists() else str(Path(__file__).resolve())
        print("  no registered multiagent server found; checking the current repo directly:")
        ok, detail = _mcp_handshake(sys.executable, [script, "--repo", str(Path(repo).resolve()), "serve-mcp"])
        print(f"  [{'OK' if ok else 'X'}] current repo -> {detail}")
        if ok:
            print("  Register it with:  multiagent.py mcp-config --write")
        return 0 if ok else 1

    print("=" * 32)
    if stats["failed"]:
        print(f"  {stats['failed']}/{stats['total']} server(s) FAILED. Re-run: multiagent.py mcp-config --write")
        return 1
    print(f"  All {stats['total']} multiagent server(s) respond - working.")
    print("  In the app you can also type /mcp in a chat to see the live connection.")
    return 0


def land(repo: Path) -> None:
    active = active_manifests(repo)
    if not active:
        print("No active tasks to land.")
        return
    by_file: dict[str, list[str]] = {}
    for m in active:
        wt = Path(m.get("worktreePath", ""))
        if not wt.exists():
            continue
        for f in worktree_changes(wt, m.get("base", "main")):
            by_file.setdefault(norm_path(f), []).append(m.get("id", ""))
    clashes = {f: ids for f, ids in by_file.items() if len(set(ids)) > 1}

    def clash_count(m):
        return sum(1 for ids in clashes.values() if m.get("id", "") in ids)

    ordered = sorted(active, key=lambda m: (clash_count(m), m.get("stream", "")))
    print("Merge plan (read-only; nothing is merged automatically):\n")
    for i, m in enumerate(ordered, 1):
        base = m.get("base", "main")
        br = m.get("branch", "")
        flag = "   <- shares files with another task" if clash_count(m) else ""
        print(f"{i}. {m.get('id')} [{m.get('stream')}]{flag}")
        print(f"     verify, then:  git checkout {base} && git merge --no-ff {br}")
    if clashes:
        print("\n! Overlapping files (merge these one at a time and resolve by hand):")
        for f, ids in sorted(clashes.items()):
            print(f"   {f}  <- " + ", ".join(sorted(set(ids))))
    print("\nAfter each merge, rebase the remaining worktrees and re-run guard + radar.")


def parse_task_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Task file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return [
            {
                "stream": d["stream"],
                "agent": d["agent"],
                "task": d["task"],
                "agent_type": d.get("agentType") or d.get("agent_type"),
                "paths": d.get("paths"),
            }
            for d in data
        ]
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        paths = None
        if len(parts) > 3 and parts[3]:
            paths = [p.strip() for p in parts[3].split(",") if p.strip()]
        out.append({"stream": parts[0], "agent": parts[1], "task": parts[2], "agent_type": None, "paths": paths})
    return out


def dispatch_from(repo: Path, path: Path, base, no_fetch, force) -> None:
    tasks = parse_task_file(path)
    if not tasks:
        raise SystemExit(f"No tasks found in {path}")
    print(f"Batch-dispatching {len(tasks)} task(s) from {path.name}:")
    ok = 0
    for t in tasks:
        ns = argparse.Namespace(
            stream=t["stream"], task=t["task"], agent=t["agent"],
            agent_type=t.get("agent_type"), paths=t.get("paths"),
            base=base, no_fetch=no_fetch, force=force, print_handoff=False,
        )
        try:
            dispatch(ns, repo)
            ok += 1
        except SystemExit as exc:
            print(f"  ! skipped {t.get('agent')}/{t.get('task')}: {exc}")
    print(f"\nBatch done: {ok}/{len(tasks)} dispatched.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate parallel AI-agent work in a Git repo.")
    parser.add_argument("--repo", default=".", help="Target repository path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("inspect")
    setup_p = sub.add_parser("setup", help="Inspect and install the universal workflow in one simple command.")
    setup_p.add_argument("--force", action="store_true")
    setup_p.add_argument("--no-agent-files", action="store_true")
    init_p = sub.add_parser("init", help="Alias for setup: inspect, then install the workflow.")
    init_p.add_argument("--force", action="store_true")
    init_p.add_argument("--no-agent-files", action="store_true")
    install_p = sub.add_parser("install")
    install_p.add_argument("--force", action="store_true")
    install_p.add_argument("--no-agent-files", action="store_true")
    sub.add_parser("doctor", help="Readiness check: is the repo ready for multi-agent work? (READY/NOT READY)")
    sub.add_parser("examples", help="Show simple user commands and CLI examples.")
    sub.add_parser("selftest", help="Run a built-in end-to-end self-test on a throwaway repo to prove the setup works.")
    ready_p = sub.add_parser("ready", help="One command: install + hooks + readiness check.")
    ready_p.add_argument("--commit", action="store_true", help="Also commit the workflow files so worktrees carry them.")

    dispatch_p = sub.add_parser("dispatch")
    dispatch_p.add_argument("--stream")
    dispatch_p.add_argument("--task")
    dispatch_p.add_argument("--agent")
    dispatch_p.add_argument("--agent-type", default=None, choices=sorted(AGENT_TYPE_NOTES), help="Runtime note. Omit to infer from the --agent name.")
    dispatch_p.add_argument("--paths", nargs="*")
    dispatch_p.add_argument("--from", dest="from_file", help="Batch: dispatch every task from a JSON or pipe-delimited file.")
    dispatch_p.add_argument("--base")
    dispatch_p.add_argument("--no-fetch", action="store_true")
    dispatch_p.add_argument("--force", action="store_true")
    dispatch_p.add_argument("--print-handoff", action="store_true")

    sub.add_parser("status")
    prompt_p = sub.add_parser("prompt", help="Print handoff text for older workflows; prefer handoff.")
    prompt_p.add_argument("--id")
    handoff_p = sub.add_parser("handoff", help="Print optional handoff text for agents that cannot read files.")
    handoff_p.add_argument("--id")
    close_p = sub.add_parser("close")
    close_p.add_argument("--id", required=True)
    close_p.add_argument("--status", default="closed", choices=["closed", "merged"])
    guard_p = sub.add_parser("guard", help="Verify active tasks stayed inside their allowed paths (anti-collision check).")
    guard_p.add_argument("--id", help="Guard a single task id. Default: all active tasks.")
    guard_p.add_argument("--staged", action="store_true", help="Pre-commit mode: check only the staged files of the current worktree.")

    sub.add_parser("install-hooks", help="Install a pre-commit guard hook so out-of-lane commits are blocked in real time.")
    cleanup_p = sub.add_parser("cleanup", help="Remove merged/closed task worktrees and branches.")
    cleanup_p.add_argument("--id")
    cleanup_p.add_argument("--force", action="store_true")
    board_p = sub.add_parser("board", help="One-screen status of every active task (dirty/ahead/behind/guard).")
    board_p.add_argument("--watch", action="store_true")
    sub.add_parser("radar", help="List files edited by more than one active task before you merge.")
    launch_p = sub.add_parser("launch", help="Print how to open each task's worktree in its program (CLI or desktop app).")
    launch_p.add_argument("--id")
    launch_p.add_argument("--open", action="store_true", dest="do_open", help="Also open each worktree in the file manager.")
    dc_p = sub.add_parser("desktop-config", help="Emit/merge a Claude Desktop filesystem-MCP config granting access to every worktree.")
    dc_p.add_argument("--config", help="Target config file (default: this OS's claude_desktop_config.json).")
    dc_p.add_argument("--write", action="store_true", help="Merge into the target config file (a .bak backup is kept).")
    dc_p.add_argument("--server-name", default="filesystem")
    serve_p = sub.add_parser("serve-mcp", help="Run as an MCP server (stdio) so Claude Desktop / Codex can use the workflow from a chat.")
    serve_p.add_argument("--allow-actions", action="store_true", help="Also expose dispatch_task/close_task write tools.")
    mcp_p = sub.add_parser("mcp-config", help="Register the workflow as MCP servers (filesystem + multiagent) for Claude Desktop / Codex.")
    mcp_p.add_argument("--config", help="Target config file (default: this OS's claude_desktop_config.json).")
    mcp_p.add_argument("--write", action="store_true", help="Merge into the target config file (a .bak backup is kept).")
    mcp_p.add_argument("--codex", action="store_true", help="Also print (and with --write, merge) the Codex config.toml block.")
    mcp_p.add_argument("--codex-config", help="Codex config file (default: ~/.codex/config.toml).")
    mcp_p.add_argument("--actions", action="store_true", help="Register the server with write tools (dispatch_task/close_task) enabled.")
    check_p = sub.add_parser("mcp-check", help="Live health check: spawn the registered MCP server(s) and confirm they respond.")
    check_p.add_argument("--config", help="Config file to read servers from (default: claude_desktop_config.json).")
    check_p.add_argument("--name", help="Check only this server name.")
    check_p.add_argument("--codex", action="store_true", help="Also check the Codex config.toml servers.")
    check_p.add_argument("--codex-config", help="Codex config file (default: ~/.codex/config.toml).")
    sub.add_parser("land", help="Print a read-only merge plan (order, overlaps, verify reminders).")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    # These do not need a target repo, so they work from anywhere.
    if args.cmd == "examples":
        examples()
        return
    if args.cmd == "selftest":
        raise SystemExit(selftest())
    if args.cmd == "serve-mcp":
        # Start the server even if the repo is unusual; tools report issues
        # instead of the server failing to launch (so the client shows connected).
        try:
            base = main_checkout(repo_root(Path(args.repo).resolve()))
        except SystemExit:
            base = Path(args.repo).resolve()
        serve_mcp(base, allow_actions=args.allow_actions)
        return
    repo = repo_root(Path(args.repo).resolve())
    # Coordination/readiness commands read manifests from the main checkout;
    # resolve it so they also work when invoked from inside a worktree.
    if args.cmd in {"board", "radar", "cleanup", "land", "launch", "status", "desktop-config",
                    "doctor", "ready", "mcp-config", "mcp-check"}:
        repo = main_checkout(repo)
    if args.cmd == "inspect":
        inspect(repo)
    elif args.cmd in {"setup", "init"}:
        inspect(repo)
        print("\n--- Installing workflow ---")
        install(repo, force=args.force, agent_files=not args.no_agent_files)
    elif args.cmd == "install":
        install(repo, force=args.force, agent_files=not args.no_agent_files)
    elif args.cmd == "doctor":
        raise SystemExit(doctor(repo))
    elif args.cmd == "ready":
        raise SystemExit(ready(repo, args.commit))
    elif args.cmd == "dispatch":
        if args.from_file:
            dispatch_from(repo, Path(args.from_file), args.base, args.no_fetch, args.force)
        else:
            missing = [n for n in ("stream", "task", "agent") if not getattr(args, n)]
            if missing:
                raise SystemExit("dispatch needs --" + ", --".join(missing) + " (or use --from <file>).")
            dispatch(args, repo)
    elif args.cmd == "status":
        status(repo)
    elif args.cmd in {"prompt", "handoff"}:
        print_handoff(repo, args.id)
    elif args.cmd == "close":
        close(repo, args.id, args.status)
    elif args.cmd == "guard":
        if args.staged:
            guard_staged(repo)
        else:
            guard(repo, args.id)
    elif args.cmd == "install-hooks":
        install_hooks(repo)
    elif args.cmd == "cleanup":
        cleanup(repo, args.id, args.force)
    elif args.cmd == "board":
        raise SystemExit(board(repo, once=not args.watch))
    elif args.cmd == "radar":
        radar(repo)
    elif args.cmd == "launch":
        launch(repo, args.id, args.do_open)
    elif args.cmd == "desktop-config":
        desktop_config(repo, args.config, args.write, args.server_name)
    elif args.cmd == "mcp-config":
        mcp_config(repo, args.config, args.write, args.codex, args.actions, args.codex_config)
    elif args.cmd == "mcp-check":
        raise SystemExit(mcp_check(repo, args.config, args.name, args.codex, args.codex_config))
    elif args.cmd == "land":
        land(repo)


if __name__ == "__main__":
    main()
