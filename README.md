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

## Desktop Apps (Claude Desktop / Codex Desktop)

Several of these agents also run as **desktop apps** — chat apps, not terminals,
so you cannot `cd` into a worktree. Name the agent so the type is clear
(`claude-desktop`, `codex-desktop`) and `launch` prints the right steps instead
of a useless `cd && claude`:

- **Claude Desktop** reaches local files through a filesystem MCP server. Run
  `python scripts/multiagent.py desktop-config --write` once — it adds every
  active worktree to your `claude_desktop_config.json` (a `.bak` is kept). After
  restarting Claude Desktop, open a chat and say *"Work on the current task in
  .agents/current-task.md"* for the worktree that task owns.
- **Codex Desktop** opens a project pinned to a folder: start a new project whose
  working directory is the printed worktree path. (Codex Desktop has had
  out-of-project edits; the worktree plus the `install-hooks` guard contain the
  blast radius.)
- **Warp** is a terminal, so the CLI flow works: `cd` into the worktree and run
  Claude Code / Codex there.

`launch` prints all of this per task; `desktop-config` prints (or `--write`
merges) the Claude Desktop filesystem config for every worktree at once.

## Proven Better Than a Shared Checkout

`multi-agent-workflow/tests/test_vs_baseline.py` is an A/B test. It reproduces
what goes wrong when two agents share one working tree — one agent's
`git add -A && git commit` sweeps in the other's in-progress files, and two edits
to the same file silently clobber each other — then runs the same two tasks with
the workflow and shows worktrees prevent both. Baseline fails 2/2; the workflow
fails 0. `tests/test_workflow.py` separately proves the features (setup, dispatch,
overlap block, guard, multi-program discovery): 35 checks.

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
  tests/
    test_workflow.py
    test_vs_baseline.py
    test_upgrade.py
```

Both test suites and the upgrade-command tests run in CI (Ubuntu/macOS/Windows)
on every push — see `.github/workflows/test.yml`.

## Portable CLI

The bundled CLI can be run directly from the skill folder:

```powershell
python multi-agent-workflow/scripts/multiagent.py --repo C:\path\to\repo inspect
python multi-agent-workflow/scripts/multiagent.py --repo C:\path\to\repo setup
```

After setup, use the repo-local copy:

```powershell
python scripts/multiagent.py init                        # setup (alias) + auto-detect streams
python scripts/multiagent.py install-hooks               # block out-of-lane commits in real time
python scripts/multiagent.py dispatch --from tasks.txt   # batch; or one --stream/--task/--agent per task
python scripts/multiagent.py board                       # one-screen status of every agent
python scripts/multiagent.py launch                      # print the open command per program
python scripts/multiagent.py guard                       # lane check (which files left their lane)
python scripts/multiagent.py radar                       # files that two tasks both edited
python scripts/multiagent.py land                        # read-only merge plan
python scripts/multiagent.py cleanup                     # remove finished worktrees + branches
```

`init` auto-detects streams; `install-hooks` enforces lanes at commit time;
`guard`/`radar`/`land` are the pre-merge checks; `cleanup` tidies up after.

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
- Run `install-hooks` once so a pre-commit hook **blocks** any out-of-lane commit
  at commit time (override with `git commit --no-verify`) — enforcement, not just
  a written rule.
- Run `multiagent.py guard` / `radar` before merge to catch any file edited
  outside its lane or touched by two tasks — verifiable, after the fact.
- Use `board` to watch every agent's status and guard state on one screen.
- Keep the main checkout for coordination and integration.
- Ask before touching protected/parked paths or production-deploy branches.

## Repository

GitHub: [peetwan/workflow_multiagents](https://github.com/peetwan/workflow_multiagents)
