# Agent Runtime Adapters

The workflow is intentionally agent-neutral. Every agent gets the same core
contract:

```text
work only in this worktree
read .agents/current-task.md
edit only these paths
avoid blocked paths
run relevant checks
report changed files, checks, risks, and PR readiness
```

Use `--agent-type` only to add a small runtime-specific reminder to the Task
Card.

## Supported Agent Types

| Agent type | Use for | Runtime note |
| --- | --- | --- |
| `generic` | Unknown agents, default | Complete Task Card; no product-specific assumptions |
| `codex` | Codex CLI/app | Use the provided worktree as the active workspace and preserve user changes |
| `claude` | Claude Desktop/Code/CLI | Open the exact worktree folder; do not work from the original checkout |
| `gemini` | Gemini CLI or IDE agent | Set shell/IDE cwd to the worktree before file operations |
| `antigravity` | Antigravity agent/workspace | Attach the generated worktree as the project workspace |
| `qwen` | Qwen coding agents | Treat the Task Card as the full task contract; avoid broad rewrites |
| `warp` | Warp terminal agent | Open the worktree folder as the Warp session; Warp reads `AGENTS.md` (and `WARP.md`) plus the Task Card |
| `openweight` | Local/open-source/openweight model agents | Use shell commands from the worktree and ask before unclear destructive actions |

`AGENTS.md` is the cross-tool standard: Claude Code, Codex, and Warp all read it,
so a worktree that carries a committed `AGENTS.md` pointing to
`.agents/current-task.md` is enough for any of those programs to discover its
task with no API.

## Minimum Task Card Contract

Do not dispatch an agent unless the Task Card includes:

- task and stream
- exact branch
- exact worktree path
- allowed paths
- blocked paths
- check expectations
- final report format

## Tool-Specific Files

Prefer a universal `AGENTS.md`, `.agents/workflow.md`,
`.agents/quickstart.md`, and per-worktree `.agents/current-task.md`.
Add tool-specific files such as `CLAUDE.md`,
`GEMINI.md`, or IDE rules only when the project already uses them or the user
asks for them. Avoid duplicating rules in many files unless the tool will
actually read them.

The installer creates lightweight adapter files by default:

```text
CLAUDE.md
GEMINI.md
ANTIGRAVITY.md
QWEN.md
WARP.md
OPENWEIGHT.md
```

These are intentionally thin. They point each agent back to `AGENTS.md`,
`.agents/workflow.md`, `.agents/quickstart.md`, and `.agents/current-task.md`
instead of creating different rules for every tool.
