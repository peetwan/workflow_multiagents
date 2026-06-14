# Repo Audit Checklist

Use this before installing or dispatching multi-agent work.

## Identify The Repo Boundary

- Confirm `git rev-parse --show-toplevel` succeeds.
- Check for nested `.git` directories and generated worktree folders.
- Confirm the branch that should be used as base, usually `main` or `master`.
- Check remotes with `git remote -v`.
- Check status with `git status --short --branch`.

Ask the user before continuing if the current folder is only a wrapper around the
actual repo, if multiple repos are present, or if the checkout has unrelated
uncommitted work that might be committed accidentally.

## Infer Streams

Look for:

- top-level app folders: `frontend`, `backend`, `api`, `web`, `app`, `server`
- service folders with `package.json`, `requirements.txt`, `pyproject.toml`,
  `Cargo.toml`, `go.mod`, or deployment config
- docs folders: `docs`, `docs_th`, `wiki`, root `README.md`
- ops folders: `.github`, `scripts`, `infra`, `deploy`, `.agents`
- parked or protected folders named by the user

Default to conservative streams:

| Stream | Typical paths | Status |
| --- | --- | --- |
| `app` | main source folders when the repo has one product | active |
| `docs` | `docs/`, root docs | shared |
| `ops` | `.github/`, `scripts/`, workflow docs | shared |

For monorepos, create one stream per product/service family.

## Define Path Ownership

Each stream needs:

- `paths`: what the agent may edit
- `blocked`: what the agent must not edit
- `status`: `active`, `shared`, or `parked`

Use exact paths for concurrent work in the same stream. Broad stream-level paths
are safer for one agent but will block useful parallelism.

## Install Decision

Install the workflow only after:

- repo root is known
- user has approved the target repo
- existing coordination files have been inspected
- generated config can be reviewed after install

Never overwrite project-specific `AGENTS.md`, PR templates, or scripts without
checking whether they contain existing local rules.

## Publish Decision

Before pushing:

- verify the branch is the intended branch
- verify whether the branch auto-deploys
- confirm tests/checks appropriate to the changed paths ran
- include generated task id and owned paths in the PR or commit summary
