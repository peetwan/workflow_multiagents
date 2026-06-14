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

- **Claude Desktop** reaches local files through MCP servers. Run
  `python scripts/multiagent.py mcp-config --write` once — it registers a
  `filesystem` server (access to every worktree) **and** a `multiagent` server
  (the workflow itself) in your `claude_desktop_config.json` (a `.bak` is kept).
  After restarting Claude Desktop you can ask, in a normal chat, *"what are my
  multi-agent tasks?"* and it reads them directly (see the MCP section below).
- **Codex Desktop** opens a project pinned to a folder: start a new project whose
  working directory is the printed worktree path. (Codex Desktop has had
  out-of-project edits; the worktree plus the `install-hooks` guard contain the
  blast radius.)
- **Warp** is a terminal, so the CLI flow works: `cd` into the worktree and run
  Claude Code / Codex there.

`launch` prints all of this per task.

## Seamless in a Chat: the multiagent MCP server

`python scripts/multiagent.py mcp-config --write` registers two MCP servers in
Claude Desktop: `filesystem` (file access to the worktrees) and `multiagent` (a
tiny stdio server that exposes the workflow). After a restart you can ask, in a
normal chat — **no terminal, no copy-paste** — things like *"what are my
multi-agent tasks?"* or *"what should I work on in this folder?"*. Claude Desktop
calls the MCP tools and reads the Task Card itself. The read tools are
`list_tasks`, `task_card`, `which_task`, `board`, `guard`, `radar`.

Add `mcp-config --actions` to also expose **write** tools — `dispatch_task` and
`close_task` — so you can set up and close tasks from the chat itself. Write
actions are **off by default** for safety. For Codex, `mcp-config --codex` prints
the `~/.codex/config.toml` block and `--codex --write` merges it in (with a
backup); Codex supports stdio MCP servers too, so the same server works there.
`mcp-check --codex` health-checks the Codex side as well.

The server is **dependency-free** (hand-rolled newline-delimited JSON-RPC) and
its tools shell out to the same tested CLI, so the server's stdout stays pure
protocol. `multiagent.py serve-mcp` is what the apps launch; you do not run it by
hand.

### Does it keep running? (reboots, app restarts)

You do not run a daemon. Claude Desktop (and Codex) **launch** the stdio server
themselves whenever the app starts, so it comes back automatically after a reboot
or an app restart — as long as the config entry stays valid. For stability the
entry uses an absolute Python path and the **repo-local** script, and each repo
gets its own `multiagent-<repo>` server so several projects coexist without
clobbering each other.

To know it is working at any moment — e.g. right after a reboot — run:

```powershell
python scripts/multiagent.py mcp-check
```

It spawns the registered server, performs a real `initialize` + `tools/list`
handshake **with a timeout** (a hung server is reported, never waited on), and
prints `[OK]` per server or the exact failure. `mcp-config --write` runs that same
check automatically after registering, and `doctor` includes a live MCP check in
its readiness report. In the app itself, typing `/mcp` in a chat shows the live
connection.

## Am I Ready? (doctor / selftest)

Two commands answer "is this set up correctly?" with no guessing:

- **`python scripts/multiagent.py doctor`** — a flutter-doctor-style checklist
  with a clear **READY / NOT READY** verdict and the exact fix for every gap:
  installed? committed to the base branch? guard hook on? `python` on PATH for
  the hook? agent CLIs found? any guard/radar issues? Claude Desktop config
  present and granting the worktrees? worktree paths free of spaces (Claude
  Desktop's filesystem MCP breaks on spaces)? It exits 0 only when ready, so it
  is scriptable.
- **`python scripts/multiagent.py selftest`** — builds a throwaway repo and
  proves the whole path on the current machine: install, isolated dispatch, and
  the pre-commit hook actually **blocking** an out-of-lane commit while allowing
  an in-lane one. Prints `SELF-TEST PASSED` or the failing step. This catches
  machine-specific issues (e.g. `python` missing from the hook's PATH).

For desktop apps the only thing a script cannot verify is the *live* connection
— confirm that in **Claude Desktop** by typing `/mcp` in a chat (the
`filesystem` server should be listed), and in **Codex Desktop** by opening the
project at the worktree path.

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

**One line, into any Git repo** (run from inside the repo):

```bash
# macOS / Linux / Git Bash
curl -fsSL https://raw.githubusercontent.com/peetwan/workflow_multiagents/main/install.sh | sh
```

```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/peetwan/workflow_multiagents/main/install.ps1 | iex
```

It drops `scripts/multiagent.py` in and runs `ready --commit` (install + guard
hook + bootstrap commit + readiness check). Set `MAW_SOURCE` to a local
`multiagent.py` to install offline.

Or install from this GitHub repository with the Codex skill installer:

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
python scripts/multiagent.py ready --commit              # one command: install + hooks + commit + READY check
python scripts/multiagent.py doctor                      # is it ready? READY / NOT READY + the fix for each gap
python scripts/multiagent.py selftest                    # prove the whole path works on THIS machine
python scripts/multiagent.py dispatch --from tasks.txt   # batch; or one --stream/--task/--agent per task
python scripts/multiagent.py board                       # one-screen status of every agent
python scripts/multiagent.py launch                      # how to open each worktree (CLI or desktop app)
python scripts/multiagent.py mcp-config --write          # Claude Desktop/Codex: file access + task tools in a chat
python scripts/multiagent.py mcp-check                   # is the MCP server alive? (run after a reboot)
python scripts/multiagent.py guard                       # lane check (which files left their lane)
python scripts/multiagent.py radar                       # files that two tasks both edited
python scripts/multiagent.py land                        # read-only merge plan
python scripts/multiagent.py cleanup                     # remove finished worktrees + branches
```

`ready` sets up everything in one command and tells you if you're READY; `doctor`
re-checks anytime; `selftest` proves the whole path (including the guard hook)
works on your machine.

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
