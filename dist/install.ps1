# install.ps1 — ATV-Phoenix installer for GitHub Copilot CLI (ATV-StarterKit-style).
# Installs the `phoenix` agent (with its inline MCP server) into ~/.copilot/agents/.
param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$bin  = Join-Path $repo "target\release\phoenix-mcp.exe"

if (-not $SkipBuild) {
    Write-Host "[phoenix] building release binary..." -ForegroundColor Cyan
    Push-Location $repo
    cargo build --release --bin phoenix-mcp | Out-Null
    Pop-Location
}
if (-not (Test-Path $bin)) { throw "phoenix-mcp.exe not found at $bin (build failed?)" }

# Stamp the real binary path into the agent definition (forward slashes, like token-master).
$agentSrc = Join-Path $PSScriptRoot "phoenix.agent.md"
$binFwd   = ($bin -replace '\\','/')
$agent    = (Get-Content $agentSrc -Raw) -replace '__PHOENIX_BIN__', $binFwd

$agentsDir = Join-Path $HOME ".copilot\agents"
New-Item -ItemType Directory -Force -Path $agentsDir | Out-Null
$dest = Join-Path $agentsDir "phoenix.agent.md"
Set-Content $dest $agent -NoNewline

Write-Host "[phoenix] installed agent -> $dest" -ForegroundColor Green
Write-Host "[phoenix] MCP server      -> $binFwd" -ForegroundColor Green
Write-Host ""
Write-Host "Restart Copilot, then run with:  copilot --agent phoenix" -ForegroundColor Yellow
Write-Host "Phoenix tools: phoenix_sense, phoenix_snapshot, phoenix_heal, phoenix_verify_trace"
