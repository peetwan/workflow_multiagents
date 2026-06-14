# Parallel Agent Workflow Patterns

## Core Model

```text
one user request -> one task card -> one agent -> one branch -> one worktree -> one manifest
```

Keep the main checkout as the integration surface. Agents work in sibling
worktrees under `_worktrees/<stream>/<task-id>/`.

## Recommended Folder Layout

```text
repo-parent/
  project/                 # main checkout
  _worktrees/
    frontend/
      20260614-claude-nav-polish/
    api/
      20260614-codex-auth-fix/
```

Runtime coordination state stays in the repo under `.agents/tasks/`, while each
worktree gets its own ignored `.agents/current-task.md` Task Card. Manifests,
handoff copies, and Task Cards are ignored by git.

## Branch Names

Use:

```text
agent/<stream>/<yyyymmdd>-<agent>-<task-slug>
```

Examples:

```text
agent/pdfm/20260614-claude-docs-deploy
agent/basket/20260614-codex-basketbuilder-risk-copy
```

## Path Ownership

Use the narrowest useful ownership:

- Best: one component file or doc file
- Good: one component folder
- Risky: whole `frontend/` or `backend/`
- High conflict: root docs, lockfiles, generated files, shared config

If a task needs shared files, assign one owner and make other agents wait.

## Mixed Agent Usage

Different programs do not share chat context. Codex, Claude, Gemini,
Antigravity, Qwen, and openweight/local agents should all open their own
generated worktree and read `.agents/current-task.md`. The Task Card must
include:

- exact worktree path
- branch
- allowed paths
- blocked paths
- verification command/expectation
- final report format

Tell each tool in natural language to work from the current Task Card. The main
checkout is for coordination and integration only. Handoff text is a fallback
for tools that cannot read files directly.

## Verification

Verification is repo-specific. Use local scripts if present, otherwise infer:

- Node: `npm run lint`, `npm run build`, project tests
- Python: `python -m compileall`, `pytest` when available
- Docs: markdown link/render sanity, no accidental code changes
- Ops: script parser/lint checks, dry-run status commands

Trading, deploy, database, billing, auth, and production paths need stronger
checks and explicit user approval before merge/push.

Always run `scripts/multiagent.py guard` from the main checkout before merging a
parallel run. It compares every active task's actual worktree changes against its
allowed paths and reports out-of-scope edits or collisions with another task's
lane, so a straying agent is caught even if it ignored the Task Card.

## Merge Order

When several agents finish together:

1. Workflow/ops changes
2. Docs-only changes
3. UI changes
4. Backend/API changes
5. High-risk production or trading changes

After every merge, rebase remaining worktrees onto the updated base branch.

## Conflict Rules

- Do not solve conflicts by deleting another agent's work.
- Stop if two tasks changed the same file.
- Merge lockfiles only after the code branch that needs them is chosen.
- Close task manifests after merge so path ownership is released.
