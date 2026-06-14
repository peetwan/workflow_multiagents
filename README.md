# Multi-Agent Workflow Skill

Installable Codex skill for designing and operating safe parallel AI-agent
workflows across Git repositories.

Skill folder:

```text
multi-agent-workflow/
```

Use with Codex skill installer from this repo:

```text
peetwan/workflow_multiagents
```

After installation, ask naturally:

```text
Use $multi-agent-workflow to inspect this repo and set up parallel Claude/Codex worktrees.
```

The skill includes a portable CLI:

```powershell
python multi-agent-workflow/scripts/multiagent.py inspect --repo C:\path\to\repo
python multi-agent-workflow/scripts/multiagent.py install --repo C:\path\to\repo
```
