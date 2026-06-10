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

# Register the phoenix MCP server in ~/.copilot/mcp-config.json so the tools auto-load in any session.
$mcpPath = Join-Path $HOME ".copilot\mcp-config.json"
$cfg = if (Test-Path $mcpPath) { Get-Content $mcpPath -Raw | ConvertFrom-Json } else { [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} } }
if (-not $cfg.PSObject.Properties.Name.Contains("mcpServers")) { $cfg | Add-Member mcpServers ([PSCustomObject]@{}) }
if ((Test-Path $mcpPath) -and -not (Test-Path "$mcpPath.phoenix-bak")) { Copy-Item $mcpPath "$mcpPath.phoenix-bak" }
$cfg.mcpServers | Add-Member -NotePropertyName "phoenix" -NotePropertyValue ([PSCustomObject]@{ type = "stdio"; command = $binFwd }) -Force
$cfg | ConvertTo-Json -Depth 10 | Set-Content $mcpPath
Write-Host "[phoenix] registered MCP server -> $mcpPath" -ForegroundColor Green

Write-Host ""
Write-Host "Restart Copilot, then run with:  copilot --agent phoenix" -ForegroundColor Yellow
Write-Host "Phoenix tools: phoenix_sense, phoenix_snapshot, phoenix_heal, phoenix_verify_trace"
