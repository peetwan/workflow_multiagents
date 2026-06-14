# User Commands And Task Cards

## Natural Language User Requests

Users can speak normally:

```text
Set up this repo so Claude, Codex, Gemini, Antigravity, and Qwen can work in
parallel without touching each other's files.
```

```text
Dispatch one Claude task for docs, one Codex task for frontend, and one Qwen
task for tests. Keep them in separate worktrees.
```

```text
Check this repo first, install the multi-agent workflow if it makes sense, then
give me task worktrees for each agent.
```

## Dispatch Examples

```powershell
python scripts/multiagent.py dispatch --stream docs --task "refresh deployment docs" --agent claude-docs --agent-type claude --paths "docs/deploy.md"
```

```powershell
python scripts/multiagent.py dispatch --stream frontend --task "mobile nav polish" --agent codex-ui --agent-type codex --paths "src/components/Nav.tsx","src/styles/nav.css"
```

```powershell
python scripts/multiagent.py dispatch --stream tests --task "add edge cases" --agent qwen-tests --agent-type qwen --paths "tests/"
```

## Natural Agent Command

After dispatch, open the generated worktree in the target agent and speak
normally:

```text
Please work on the current task in `.agents/current-task.md`.
Follow the repo workflow and stay inside the allowed paths.
```

Use the `handoff` command only when an agent cannot read files from the worktree
and needs handoff text pasted manually.

## Generated Task Card Shape

```text
# Current Agent Task

You are working as: claude-docs
Agent runtime: claude
Task: refresh deployment docs
Stream: docs
Branch: agent/docs/20260614-claude-docs-refresh-deployment-docs
Use this worktree only:
C:\path\to\_worktrees\docs\20260614-claude-docs-refresh-deployment-docs

Before touching files:
1. Read AGENTS.md if present.
2. Read .agents/workflow.md if present.
3. Treat this file as the source of truth for this worktree's current task.
4. Run git status --short --branch.

Allowed paths:
- docs/deploy.md

Do not touch:
- src/
- backend/
- infra/

Before final answer:
- Run relevant checks for the changed files.
- Report changed files, checks, risks, and whether the branch is PR-ready.
```

## User Follow-Up After Agents Finish

```text
Claude, Codex, and Qwen are done. Inspect all branches, verify checks, then
merge or commit/push the completed work to GitHub.
```
