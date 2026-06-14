# User And Agent Prompt Examples

## Natural Language User Requests

Users can speak normally:

```text
Set up this repo so Claude and Codex can work in parallel without touching each
other's files.
```

```text
Dispatch one Claude task for PDFM docs and one Codex task for basket frontend.
Keep them in separate worktrees.
```

```text
Check this repo first, install the multi-agent workflow if it makes sense, then
give me copy-paste prompts for each agent.
```

## Dispatch Examples

```powershell
python scripts/multiagent.py dispatch --stream docs --task "refresh deployment docs" --agent claude-docs --paths "docs/deploy.md"
```

```powershell
python scripts/multiagent.py dispatch --stream frontend --task "mobile nav polish" --agent codex-ui --paths "src/components/Nav.tsx","src/styles/nav.css"
```

## Generated Agent Prompt Shape

```text
You are working as: claude-docs
Task: refresh deployment docs
Stream: docs
Branch: agent/docs/20260614-claude-docs-refresh-deployment-docs
Use this worktree only:
C:\path\to\_worktrees\docs\20260614-claude-docs-refresh-deployment-docs

Before touching files:
1. Read AGENTS.md if present.
2. Read .agents/workflow.md if present.
3. Run git status --short --branch.

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
Claude and Codex are done. Inspect both branches, verify checks, then merge or
commit/push the completed work to GitHub.
```
