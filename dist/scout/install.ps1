# dist/scout/install.ps1 — ATV-Phoenix Scout adapter installer
#
# Installs Phoenix into Microsoft Scout:
#   1. Verifies the phoenix-mcp binary is accessible (PATH or explicit path)
#   2. Installs the phoenix-self-heal skill to ~/.copilot/skills/phoenix-self-heal/SKILL.md
#   3. Runs a smoke sense check to verify the install is functional
#
# Usage:
#   .\install.ps1                          # Binary must be on PATH
#   .\install.ps1 -BinPath "C:\...\phoenix-mcp.exe"   # Explicit path
#
# Scout adapter notes:
#   Scout uses CLI tools + skills (not external MCP servers).
#   Phoenix ships as: phoenix-mcp binary (tool) + phoenix-self-heal.skill.md (Scout skill)
#   PHOENIX_WORKSPACE sets the project root for phoenix-mcp operations.
#   See dist/scout/README.md for full details.

param(
    [string]$BinPath = ""
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

# --- 1. Resolve phoenix-mcp binary ---
$bin = if ($BinPath) {
    $BinPath
} elseif (Get-Command phoenix-mcp -ErrorAction SilentlyContinue) {
    (Get-Command phoenix-mcp).Source
} else {
    # Default: relative to repo root (when installing from a clone)
    $repoRoot = Split-Path -Parent $here | Split-Path -Parent
    $candidate = Join-Path $repoRoot "target\release\phoenix-mcp.exe"
    if (Test-Path $candidate) { $candidate } else { $null }
}

if (-not $bin -or -not (Test-Path $bin)) {
    throw @"
phoenix-mcp.exe not found. Options:
  1. Run 'cargo build --release' in the repo first, then re-run this installer.
  2. Pass -BinPath <path\to\phoenix-mcp.exe> explicitly.
  3. Add phoenix-mcp.exe to your PATH.
"@
}
Write-Host "[phoenix-scout] binary found at: $bin" -ForegroundColor Green

# --- 2. Install phoenix-self-heal Scout skill ---
$skillSrc = Join-Path $here "phoenix-self-heal.skill.md"
if (-not (Test-Path $skillSrc)) {
    throw "phoenix-self-heal.skill.md not found at $skillSrc"
}

$skillsDir = Join-Path $HOME ".copilot\skills\phoenix-self-heal"
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
$skillDest = Join-Path $skillsDir "SKILL.md"
Copy-Item -Force $skillSrc $skillDest
Write-Host "[phoenix-scout] installed Scout skill -> $skillDest" -ForegroundColor Green

# --- 3. Smoke sense check (trivially-passing command_exit check) ---
$smokeCheck = [PSCustomObject]@{
    kind   = "command_exit"
    target = @("python", "--version")
    expect = 0
}
$tmpCheck = [System.IO.Path]::GetTempFileName() -replace '\.tmp$', '.json'
$smokeCheck | ConvertTo-Json | Set-Content $tmpCheck -Encoding UTF8

try {
    $result = & $bin sense "@$tmpCheck" 2>&1
    $parsed = $result | ConvertFrom-Json -ErrorAction SilentlyContinue
    if ($parsed -and $parsed.ok -eq $true) {
        Write-Host "[phoenix-scout] smoke sense: OK" -ForegroundColor Green
    } else {
        Write-Warning "[phoenix-scout] smoke sense: unexpected result: $result"
    }
} finally {
    Remove-Item $tmpCheck -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Phoenix Scout adapter installed." -ForegroundColor Yellow
Write-Host "  Binary    : $bin"
Write-Host "  Scout skill: $skillDest"
Write-Host ""
Write-Host "In any Scout session, invoke with: /phoenix-self-heal"
Write-Host "Set PHOENIX_WORKSPACE=<repo-root> before calling phoenix-mcp for context."
