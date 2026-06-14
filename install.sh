#!/bin/sh
# One-line installer for the multi-agent workflow.
#
#   curl -fsSL https://raw.githubusercontent.com/peetwan/workflow_multiagents/main/install.sh | sh
#
# Run it from inside the Git repo you want to set up. It drops scripts/multiagent.py
# in, then runs `ready --commit` (install + real-time guard hook + bootstrap commit
# + readiness check). Set MAW_SOURCE=/path/to/multiagent.py to install from a local
# copy instead of downloading (offline / testing).
set -e

REPO_RAW="https://raw.githubusercontent.com/peetwan/workflow_multiagents/main"
SCRIPT_URL="$REPO_RAW/multi-agent-workflow/scripts/multiagent.py"

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Not a Git repository. cd into your project (or run: git init) first." >&2
  exit 1
fi
ROOT="$(git rev-parse --show-toplevel)"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "Python not found on PATH. Install Python 3 and try again." >&2
  exit 1
fi

mkdir -p "$ROOT/scripts"
DEST="$ROOT/scripts/multiagent.py"

if [ -n "$MAW_SOURCE" ] && [ -f "$MAW_SOURCE" ]; then
  echo "Installing multiagent.py from $MAW_SOURCE ..."
  cp "$MAW_SOURCE" "$DEST"
elif command -v curl >/dev/null 2>&1; then
  echo "Downloading multiagent.py ..."
  curl -fsSL "$SCRIPT_URL" -o "$DEST"
elif command -v wget >/dev/null 2>&1; then
  echo "Downloading multiagent.py ..."
  wget -qO "$DEST" "$SCRIPT_URL"
else
  echo "Need curl or wget (or set MAW_SOURCE to a local multiagent.py)." >&2
  exit 1
fi

echo "Setting up the workflow ..."
"$PY" "$DEST" --repo "$ROOT" ready --commit

echo
echo "Installed. Next:"
echo "  $PY scripts/multiagent.py dispatch --stream <stream> --task \"...\" --agent <name>"
echo "  $PY scripts/multiagent.py mcp-config --write    # connect Claude Desktop / Codex"
echo "  $PY scripts/multiagent.py doctor                # re-check readiness anytime"
