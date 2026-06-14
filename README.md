# Multi-Agent Workflow Skill

Codex-installable skill plus agent-neutral workflow runtime for designing and
operating safe parallel AI-agent workflows across Git repositories. The workflow
is meant for Codex, Claude, Gemini, Antigravity, Qwen, openweight/open-source
coding models, and any other agent that can follow a prompt and work in a Git
worktree.

Skill folder:

```text
multi-agent-workflow/
```

Install with the Codex skill installer from this repo:

```text
peetwan/workflow_multiagents
```

After installation, ask naturally:

```text
Use $multi-agent-workflow to inspect this repo and set up parallel Codex, Claude, Gemini, Antigravity, and Qwen worktrees.
```

The skill includes a portable CLI:

```powershell
python multi-agent-workflow/scripts/multiagent.py inspect --repo C:\path\to\repo
python multi-agent-workflow/scripts/multiagent.py install --repo C:\path\to\repo
```

After installation in a project, dispatch any agent runtime:

```powershell
python scripts/multiagent.py dispatch --stream frontend --task "nav polish" --agent claude-a --agent-type claude --paths "src/Nav.tsx"
python scripts/multiagent.py dispatch --stream tests --task "edge cases" --agent qwen-a --agent-type qwen --paths "tests/"
```
