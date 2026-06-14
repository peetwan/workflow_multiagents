# One-line installer for the multi-agent workflow (Windows PowerShell).
#
#   irm https://raw.githubusercontent.com/peetwan/workflow_multiagents/main/install.ps1 | iex
#
# Run it from inside the Git repo you want to set up. It drops scripts\multiagent.py
# in, then runs `ready --commit` (install + real-time guard hook + bootstrap commit
# + readiness check). Set $env:MAW_SOURCE to a local multiagent.py to install from a
# local copy instead of downloading (offline / testing).
$ErrorActionPreference = "Stop"

$RepoRaw = "https://raw.githubusercontent.com/peetwan/workflow_multiagents/main"
$ScriptUrl = "$RepoRaw/multi-agent-workflow/scripts/multiagent.py"

$root = $null
try { $root = (& git rev-parse --show-toplevel 2>$null) } catch { $root = $null }
if (-not $root) {
  Write-Error "Not a Git repository. cd into your project (or run: git init) first."
  exit 1
}
$root = $root.Trim()

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $py) {
  Write-Error "Python not found on PATH. Install Python 3 and try again."
  exit 1
}

New-Item -ItemType Directory -Force -Path "$root\scripts" | Out-Null
$dest = "$root\scripts\multiagent.py"

if ($env:MAW_SOURCE -and (Test-Path $env:MAW_SOURCE)) {
  Write-Host "Installing multiagent.py from $($env:MAW_SOURCE) ..."
  Copy-Item -Path $env:MAW_SOURCE -Destination $dest -Force
}
else {
  Write-Host "Downloading multiagent.py ..."
  Invoke-WebRequest -UseBasicParsing -Uri $ScriptUrl -OutFile $dest
}

Write-Host "Setting up the workflow ..."
& $py $dest --repo $root ready --commit
if ($LASTEXITCODE -ne 0) { Write-Error "Setup failed (exit $LASTEXITCODE)."; exit $LASTEXITCODE }

Write-Host ""
Write-Host "Installed. Next:"
Write-Host "  python scripts\multiagent.py dispatch --stream <stream> --task '...' --agent <name>"
Write-Host "  python scripts\multiagent.py mcp-config --write    # connect Claude Desktop / Codex"
Write-Host "  python scripts\multiagent.py doctor                # re-check readiness anytime"
