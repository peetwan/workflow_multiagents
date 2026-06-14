---
name: multi-agent-workflow
description: Design, install, and operate safe, agent-neutral parallel AI workflows across any Git repository. Use when the user wants to speak in natural language and have multiple coding agents — including separate programs driven by hand with no API, such as Claude Code, Codex, and Warp, plus Gemini, Antigravity, Qwen, or openweight/open-source models — work at the same time without overwriting each other; wants a universal worktree/branch/task-card dispatch system; wants repo-local adapter files such as AGENTS.md, CLAUDE.md, GEMINI.md, ANTIGRAVITY.md, QWEN.md, WARP.md, or OPENWEIGHT.md; wants path ownership, preflight checks, or GitHub publishing guidance for multi-agent development.
---

# Multi-Agent Workflow

Use this skill to turn any Git repository into a safe workspace for parallel AI
agents. The user can speak naturally. The workflow turns that request into
worktrees, branches, manifests, and per-worktree Task Cards. It is
agent-neutral: Claude Code, Codex, Warp, Gemini, Antigravity, Qwen, and
openweight coding agents all receive the same work contract and work in separate
worktrees.

No API or orchestrator service is required. Everything is plain files in Git
worktrees, so it works when the user drives several separate programs by hand.
`AGENTS.md` is the cross-tool anchor — Claude Code, Codex, and Warp all read it
(Claude Code also reads `CLAUDE.md`, Warp also reads `WARP.md`). Once those files
are committed, opening a worktree in any program leads it from `AGENTS.md` to
`.agents/current-task.md`. The default design is:

```text
one user request = one task card = one agent = one branch = one worktree = one manifest
```

## Seamless Mode (Start Here)

This is the 90% path. The user speaks plainly; you (the orchestrating agent) run
at most one command per task. The user never memorizes the CLI.

When the user asks for parallel agents (e.g. "let Claude do the docs and Codex do
the frontend without clashing"):

1. **Set up once.** If `.agents/workflow-config.toml` is missing, run
   `python <skill>/scripts/multiagent.py init --repo <repo>`. `init` inspects the
   repo, auto-detects streams from the folder layout, and installs the
   coordination files. Skim the generated config; fix streams only if detection
   is wrong.

2. **Dispatch one task per agent.** The minimum is three flags — the agent type
   is inferred from the agent name and paths default to the stream's:

   ```powershell
   python scripts/multiagent.py dispatch --stream <stream> --task "<short task>" --agent <name>
   ```

   Add `--paths <files-or-folders>` to narrow ownership when several agents share
   a stream. Overlapping paths with another active task are refused
   automatically, so two agents can never be put on the same files by accident.

3. **Hand off in one sentence.** Tell the user which folder to open in each agent
   and to say: *"Work on the current task in `.agents/current-task.md`."* That
   file is the full contract (worktree, allowed paths, blocked paths, report
   format) — no long prompt to paste.

4. **Guard before merge.** After agents finish, from the main checkout run
   `python scripts/multiagent.py guard`. It reports any file edited outside an
   agent's allowed paths and flags collisions with another task's lane. Re-scope
   or move the work before merging.

Everything below is the detailed reference for when the seamless path needs
adjusting.

## When This Helps (And When It Is Overhead)

Use it when two or more agents work the same repo at once and could touch
overlapping files — isolated worktrees plus `guard` are exactly what protect that
case, which a shared working tree cannot. For a single agent, or work in
obviously separate folders/repos that will not collide, the worktree setup is not
worth it; edit directly. This skill exists to make parallel work safe, not to add
ceremony to simple work.

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
   `web`, `api`, `docs`, or `ops` — whatever the repo's folders imply. Each
   stream must define:

   - status: `active`, `shared`, or `parked`
   - owned paths
   - blocked/protected paths
   - verification expectation

   Read `references/repo-audit.md` for the inspection checklist and
   `references/parallel-patterns.md` for stream design patterns.

3. **Install repo-local coordination files.**
   Prefer the script for deterministic setup:

   ```powershell
   python <skill>/scripts/multiagent.py setup --repo <repo>
   ```

   This creates `.agents/`, `.agents/workflow-config.toml`,
   `.agents/workflow.md`, `.agents/quickstart.md`, a local
   `scripts/multiagent.py`, runtime ignore rules, universal `AGENTS.md`, and
   adapter files for Claude, Gemini, Antigravity, Qwen, and openweight/local
   agents. Review the generated config before using broad streams.

4. **Dispatch agents with narrow paths and Task Cards.**
   Prefer exact files or folders for concurrent work in the same stream:

   ```powershell
   python scripts/multiagent.py dispatch --stream frontend --task "mobile nav polish" --agent claude-a --paths "src/components/Nav.tsx"
   ```

   The dispatcher creates the worktree, branch, local manifest, and
   `worktree/.agents/current-task.md`. It refuses overlapping active manifests
   unless `--force` is used intentionally.

5. **Let the agent read the Task Card.**
   Open the generated worktree in Codex, Claude, Gemini, Antigravity, Qwen, or
   an openweight CLI/IDE agent and speak normally, for example: "work on the
   current task in `.agents/current-task.md`." The Task Card contains the exact
   worktree path, allowed paths, blocked paths, and final report requirements.
   Use `--agent-type` when dispatching if a runtime-specific note would help:

   ```powershell
   python scripts/multiagent.py dispatch --stream frontend --task "nav polish" --agent qwen-a --agent-type qwen --paths "src/Nav.tsx"
   ```

6. **Guard, then verify before publishing.**
   From the main checkout run `python scripts/multiagent.py guard` to confirm
   every active task changed only files inside its allowed paths — it flags
   out-of-scope edits and collisions with another task's lane, and exits
   non-zero on any violation. Then run repo-specific checks inside the agent
   worktree. If the user asks to push to GitHub, commit intentionally and push
   the branch requested by the user. Do not push a production/deploy-tracked
   branch unless the user explicitly asked.

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

- `scripts/multiagent.py`: cross-project CLI for inspect, setup/init, install,
  doctor, examples, dispatch, status, task handoff, guard (anti-collision
  check), and close operations.
- `tests/test_workflow.py`: end-to-end test on a throwaway repo proving universal
  setup, one-line dispatch, dispatch-time overlap blocking, and guard catching
  out-of-lane edits. Run `python tests/test_workflow.py`.
- `references/repo-audit.md`: repo inspection and install decision checklist.
- `references/parallel-patterns.md`: detailed workflow patterns and merge rules.
- `references/agent-adapters.md`: notes for Codex, Claude, Gemini,
  Antigravity, Qwen, and openweight/local agents.
- `references/user-prompts.md`: natural-language user commands and Task Card
  handoff examples.
