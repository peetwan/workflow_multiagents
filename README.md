# Multi-Agent Workflow Skill

Universal workflow/worktree coordination for running multiple AI coding agents
against the same Git repository without overwriting each other.

This repository contains an installable Codex skill and a portable, dependency
free Python runtime. It also generates repo-local adapter files for Claude,
Gemini, Antigravity, Qwen, openweight/open-source coding models, and any other
agent that can work from a Git worktree.

## What It Solves

When several agents work in one project at the same time, the hard parts are not
usually the edits themselves. The hard parts are coordination:

- which agent owns which files
- where each agent should work
- how to avoid overlapping edits
- how to keep the main checkout clean
- how to merge and publish safely
- how to make different tools follow the same rules

This skill standardizes that into one contract:

```text
one user request = one task card = one agent = one branch = one worktree = one manifest
```

## User Experience

The user should speak normally:

```text
Set up this repo so Claude Code, Codex, and Warp can work in parallel safely.
```

```text
Dispatch Claude Code for docs, Codex for frontend, and Warp for the API.
```

The workflow creates isolated worktrees and writes a Task Card into each
worktree:

```text
.agents/current-task.md
```

Then the user can open that worktree in any agent runtime and say:

```text
Please work on the current task in .agents/current-task.md.
```

No long copy-paste prompt is required for the normal flow. A handoff text file
is still generated as a fallback for tools that cannot read files directly.

## No API Needed — Drive Separate Programs By Hand

You do not need an API or an orchestrator service. The whole system is plain
files in Git worktrees, so it works when you personally drive several separate
programs — Claude Code, Codex, and Warp — each in its own window.

`AGENTS.md` is the shared standard: Claude Code, Codex, and Warp all read it
(Claude Code also reads `CLAUDE.md`, Warp also reads `WARP.md`). Commit these
once and every worktree carries them, so when you open a worktree folder in any
program it reads `AGENTS.md` -> `.agents/current-task.md` and knows exactly what
to do.

A hand-driven session:

```powershell
# In any terminal, set up once and dispatch one task per program:
python scripts/multiagent.py init
python scripts/multiagent.py dispatch --stream docs     --task "rewrite README" --agent claude
python scripts/multiagent.py dispatch --stream frontend --task "polish nav"     --agent codex
python scripts/multiagent.py dispatch --stream api      --task "rate limiting"   --agent warp
```

Each dispatch prints a worktree folder. Open it in its program (Claude Code /
Codex / Warp) and say: "Work on the current task in .agents/current-task.md."
When they finish, run `python scripts/multiagent.py guard` to confirm none of
them edited outside its lane, then merge. Commit the workflow files once before
dispatching (the installer creates them); `dispatch` warns if you forget.

## Agent Support

The workflow is not limited to one tool. Installing it into a project creates a
universal `AGENTS.md` plus thin tool-specific entry files:

```text
AGENTS.md       <- Claude Code, Codex, and Warp all read this
CLAUDE.md       <- Claude Code
GEMINI.md       <- Gemini
ANTIGRAVITY.md  <- Antigravity
QWEN.md         <- Qwen
WARP.md         <- Warp
OPENWEIGHT.md   <- local / open-weight agents
```

These files all point agents to the same source of truth:

```text
.agents/workflow.md
.agents/quickstart.md
.agents/current-task.md
```

That means the user can use the same simple instruction everywhere:

```text
Please work on the current task in .agents/current-task.md.
```

## Install The Skill

Install from this GitHub repository with the Codex skill installer:

```text
peetwan/workflow_multiagents
```

Then invoke it naturally:

```text
Use $multi-agent-workflow to inspect this repo and set up parallel agent worktrees.
```

## Skill Contents

```text
multi-agent-workflow/
  SKILL.md
  agents/openai.yaml
  references/
    agent-adapters.md
    parallel-patterns.md
    repo-audit.md
    user-prompts.md
  scripts/
    multiagent.py
```

## Portable CLI

The bundled CLI can be run directly from the skill folder:

```powershell
python multi-agent-workflow/scripts/multiagent.py --repo C:\path\to\repo inspect
python multi-agent-workflow/scripts/multiagent.py --repo C:\path\to\repo setup
```

After setup, use the repo-local copy:

```powershell
python scripts/multiagent.py setup
python scripts/multiagent.py doctor
python scripts/multiagent.py status
python scripts/multiagent.py dispatch --stream frontend --task "nav polish" --agent claude-a --agent-type claude --paths "src/Nav.tsx"
python scripts/multiagent.py dispatch --stream tests --task "edge cases" --agent qwen-a --agent-type qwen --paths "tests/"
python scripts/multiagent.py guard
```

`setup` has an `init` alias. `guard` verifies, before merge, that each agent
only touched files inside its allowed paths.

Supported `--agent-type` values:

```text
generic, codex, claude, gemini, antigravity, qwen, warp, openweight
```

## Generated Project Files

Installing into a project creates:

```text
.agents/
  workflow.md
  workflow-config.toml
  quickstart.md
  tasks/
  locks/
scripts/
  multiagent.py
AGENTS.md
CLAUDE.md
GEMINI.md
ANTIGRAVITY.md
QWEN.md
WARP.md
OPENWEIGHT.md
```

Runtime files are ignored by git:

```text
.agents/current-task.md
.agents/tasks/*.json
.agents/tasks/*.handoff.md
.agents/locks/*.lock
```

## Safety Model

- Inspect the repo before installing.
- Use one branch and one worktree per task.
- Use narrow path ownership whenever agents run in parallel.
- Block overlapping active task manifests at dispatch time.
- Run `multiagent.py guard` before merge to catch any agent that edited outside
  its allowed paths or collided with another task's lane — verifiable, not just a
  written rule.
- Keep the main checkout for coordination and integration.
- Ask before touching protected/parked paths or production-deploy branches.

## Repository

GitHub: [peetwan/workflow_multiagents](https://github.com/peetwan/workflow_multiagents)
