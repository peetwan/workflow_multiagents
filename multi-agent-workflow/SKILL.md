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
   `python <skill>/scripts/multiagent.py init --repo <repo>` (auto-detects streams
   and installs coordination files), then `python scripts/multiagent.py
   install-hooks` once. The hook makes the rest enforce itself: any commit that
   strays outside a task's lane is blocked at commit time, not just caught later.

2. **Dispatch.** One task per agent — three flags (type inferred, paths default):

   ```powershell
   python scripts/multiagent.py dispatch --stream <stream> --task "<short task>" --agent <name>
   ```

   Or set up several at once from a file —
   `python scripts/multiagent.py dispatch --from tasks.txt`
   (each line: `stream | agent | task | path1,path2`). Overlapping paths with
   another active task are refused automatically.

3. **Hand off in one sentence.** Tell the user which folder to open in each agent
   (`python scripts/multiagent.py launch` prints the exact open command per
   program) and to say: *"Work on the current task in `.agents/current-task.md`."*

4. **Watch, then land.** `python scripts/multiagent.py board` (add `--watch`)
   shows every agent's status and guard state on one screen. Before merging, run
   `guard` (lane check), `radar` (files that two tasks both edited), and `land`
   (a read-only merge plan). After merge, `cleanup` removes finished worktrees
   and branches.

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

- `scripts/multiagent.py`: cross-project CLI. Setup: `inspect`, `setup`/`init`,
  `install`, `install-hooks`, `doctor`, `examples`. Run: `dispatch` (incl.
  `--from` batch), `status`, `board` (`--watch`), `launch`, `handoff`. Safety:
  `guard` (and `guard --staged` for the pre-commit hook), `radar` (cross-task
  file overlap). Finish: `land` (merge plan), `close`, `cleanup`.
- `tests/test_workflow.py`: end-to-end test on a throwaway repo proving universal
  setup, one-line dispatch, dispatch-time overlap blocking, guard catching
  out-of-lane edits, and multi-program discovery. Run `python tests/test_workflow.py`.
- `tests/test_upgrade.py`: tests the upgrade commands — real-time pre-commit
  block, board, radar, batch dispatch, launch, land, cleanup. Run
  `python tests/test_upgrade.py`.
- `tests/test_vs_baseline.py`: A/B test proving the workflow beats NOT using it.
  It reproduces the two failures of a shared working tree (one agent's commit
  sweeping in another's in-progress files; silent same-file clobber) and shows
  worktrees prevent both. Run `python tests/test_vs_baseline.py`.
- `references/repo-audit.md`: repo inspection and install decision checklist.
- `references/parallel-patterns.md`: detailed workflow patterns and merge rules.
- `references/agent-adapters.md`: notes for Codex, Claude, Gemini,
  Antigravity, Qwen, and openweight/local agents.
- `references/user-prompts.md`: natural-language user commands and Task Card
  handoff examples.
