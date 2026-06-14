---
name: multi-agent-workflow
description: Design, install, and operate safe, agent-neutral parallel AI workflows across any Git repository. Use when the user wants multiple Codex, Claude, Gemini, Antigravity, Qwen, openweight/open-source models, or other coding agents to work at the same time without overwriting each other; wants a universal worktree/branch/task dispatch system; wants reusable cross-agent prompts, path ownership, repo-local coordination files, preflight checks, or GitHub publishing guidance for multi-agent development.
---

# Multi-Agent Workflow

Use this skill to turn any Git repository into a safe workspace for parallel AI
agents. It is agent-neutral: Codex, Claude, Gemini, Antigravity, Qwen, and
openweight coding agents all receive the same work contract and work in separate
worktrees. The default design is:

```text
one user task = one agent = one branch = one worktree = one path ownership manifest
```

## Required Workflow

1. **Inspect before installing or dispatching.**
   Run the bundled inspector against the target repo:

   ```powershell
   python <skill>/scripts/multiagent.py inspect --repo <repo>
   ```

   If the repo boundaries, active product areas, protected paths, deploy branch,
   or dirty worktree state are unclear, ask the user before installing or
   dispatching broad work.

2. **Design streams and path ownership.**
   Streams are product or responsibility areas such as `frontend`, `backend`,
   `docs`, `ops`, `basket`, `pdfm`, or `api`. Each stream must define:

   - status: `active`, `shared`, or `parked`
   - owned paths
   - blocked/protected paths
   - verification expectation

   Read `references/repo-audit.md` for the inspection checklist and
   `references/parallel-patterns.md` for stream design patterns.

3. **Install repo-local coordination files.**
   Prefer the script for deterministic setup:

   ```powershell
   python <skill>/scripts/multiagent.py install --repo <repo>
   ```

   This creates `.agents/`, `.agents/workflow-config.toml`,
   `.agents/workflow.md`, a local `scripts/multiagent.py`, runtime ignore rules,
   and non-destructive agent guidance. Review the generated config before using
   broad streams.

4. **Dispatch agents with narrow paths.**
   Prefer exact files or folders for concurrent work in the same stream:

   ```powershell
   python scripts/multiagent.py dispatch --stream pdfm --task "mobile ticker polish" --agent claude-a --paths "pdfm-dashboard/src/components/TickerList.tsx"
   ```

   The dispatcher creates the worktree, branch, local manifest, and prompt. It
   refuses overlapping active manifests unless `--force` is used intentionally.

5. **Use generated prompts for any agent runtime.**
   For Codex, Claude, Gemini, Antigravity, Qwen, or an openweight CLI/IDE agent,
   paste the generated prompt into that program. The prompt must include the
   exact worktree path, allowed paths, blocked paths, and final reporting
   requirements. Use `--agent-type` when dispatching if a runtime-specific note
   would help:

   ```powershell
   python scripts/multiagent.py dispatch --stream frontend --task "nav polish" --agent qwen-a --agent-type qwen --paths "src/Nav.tsx"
   ```

6. **Verify before publishing.**
   Run repo-specific checks inside the agent worktree. If the user asks to push
   to GitHub, commit intentionally and push the branch requested by the user. Do
   not push a production/deploy-tracked branch unless the user explicitly asked.

## When To Ask The User

Ask before proceeding when:

- the target folder is not a Git repo or has nested repos
- the base branch or deploy-tracked branch is unclear
- the repo has uncommitted user work that might be included accidentally
- streams cannot be inferred from folder names and docs
- a task needs a parked/protected path
- two active manifests overlap and the user has not chosen which task owns it
- installation would overwrite an existing `AGENTS.md`, `.github` template, or
  project-specific workflow
- pushing could deploy production or merge unfinished work

## Bundled Resources

- `scripts/multiagent.py`: cross-project CLI for inspect, install, dispatch,
  status, prompt, and close operations.
- `references/repo-audit.md`: repo inspection and install decision checklist.
- `references/parallel-patterns.md`: detailed workflow patterns and merge rules.
- `references/agent-adapters.md`: notes for Codex, Claude, Gemini,
  Antigravity, Qwen, and openweight/local agents.
- `references/user-prompts.md`: natural-language prompts for users and generated
  agent prompt examples.
