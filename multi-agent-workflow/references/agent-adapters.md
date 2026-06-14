# Agent Runtime Adapters

The workflow is intentionally agent-neutral. Every agent gets the same core
contract:

```text
work only in this worktree
edit only these paths
avoid blocked paths
run relevant checks
report changed files, checks, risks, and PR readiness
```

Use `--agent-type` only to add a small runtime-specific reminder.

## Supported Agent Types

| Agent type | Use for | Runtime note |
| --- | --- | --- |
| `generic` | Unknown agents, default | Complete prompt; no product-specific assumptions |
| `codex` | Codex CLI/app | Use the provided worktree as the active workspace and preserve user changes |
| `claude` | Claude Desktop/Code/CLI | Open the exact worktree folder; do not work from the original checkout |
| `gemini` | Gemini CLI or IDE agent | Set shell/IDE cwd to the worktree before file operations |
| `antigravity` | Antigravity agent/workspace | Attach the generated worktree as the project workspace |
| `qwen` | Qwen coding agents | Treat the prompt as the full task contract; avoid broad rewrites |
| `openweight` | Local/open-source/openweight model agents | Use shell commands from the worktree and ask before unclear destructive actions |

## Minimum Prompt Contract

Do not dispatch an agent unless the prompt includes:

- task and stream
- exact branch
- exact worktree path
- allowed paths
- blocked paths
- check expectations
- final report format

## Tool-Specific Files

Prefer a universal `AGENTS.md` and `.agents/workflow.md` in the repo. Add
tool-specific files such as `CLAUDE.md`, `GEMINI.md`, or IDE rules only when the
project already uses them or the user asks for them. Avoid duplicating rules in
many files unless the tool will actually read them.
