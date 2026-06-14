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
Set up this repo so Claude, Codex, and Qwen can work in parallel safely.
```

```text
Dispatch Claude for docs, Codex for frontend, and Qwen for tests.
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

## Agent Support

The workflow is not limited to Codex. Installing it into a project creates
universal and tool-specific entry files:

```text
AGENTS.md
CLAUDE.md
GEMINI.md
ANTIGRAVITY.md
QWEN.md
OPENWEIGHT.md
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
```

Supported `--agent-type` values:

```text
generic, codex, claude, gemini, antigravity, qwen, openweight
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
- Block overlapping active task manifests by default.
- Keep the main checkout for coordination and integration.
- Ask before touching protected/parked paths or production-deploy branches.

## Repository

GitHub: [peetwan/workflow_multiagents](https://github.com/peetwan/workflow_multiagents)
