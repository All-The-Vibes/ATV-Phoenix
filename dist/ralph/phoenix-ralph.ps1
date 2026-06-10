#requires -Version 5
<#
.SYNOPSIS
  ATV-Phoenix Ralph loop driver — Geoffrey Huntley's `while :; do cat PROMPT.md | agent; done`
  (https://ghuntley.com/ralph), Phoenix-gated.

.DESCRIPTION
  The DRIVER decides completion, not the agent. Each loop runs the coding agent (GitHub Copilot CLI)
  with a fixed PROMPT in a FRESH context. The filesystem (.phoenix-ralph/) is the brain. The loop
  stops only when the top-level acceptance check is proven FAILURE-FIRST satisfied
  (red->green, currently green) on an intact tamper-evident trace -- via `phoenix-mcp accept`.

  Honest framing: each `copilot -p` is one-shot, so this external loop IS the persistence mechanism
  (Copilot has no Claude-Code-style re-injection hook). The agent proposes state changes; the driver
  proves them.

.NOTES
  State dir layout (.phoenix-ralph/):
    PROMPT.md        fixed per-loop instructions (re-read every iteration)
    backlog.json     [{id,title,check:<phoenix_sense Check>,done:bool}] -- each item gate is OBJECTIVE
    progress.md      append-only cross-iteration learnings (survives the fresh context)
    done-check.json  the single top-level acceptance Check that ends the loop when proven
    completed.json   written by the DRIVER on success (proof bundle) -- never by the agent
#>
[CmdletBinding()]
param(
  [string]$Dir = ".phoenix-ralph",
  [int]$MaxLoops = 50,
  [int]$MaxMinutes = 120,
  [int]$NoProgressStop = 3,
  [string]$PhoenixBin = "",
  [string]$Copilot = "",
  [switch]$AllowPreGreen,
  [switch]$NoTag
)

$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "[ralph] $m" -ForegroundColor Cyan }
function Warn($m){ Write-Host "[ralph] $m" -ForegroundColor Yellow }
function Die($m){ Write-Host "[ralph] FATAL: $m" -ForegroundColor Red; exit 2 }
function FileSig($p){ if (Test-Path $p) { (Get-FileHash $p -Algorithm SHA256).Hash } else { "absent" } }

$repo = (Get-Location).Path
$state = Join-Path $repo $Dir
$doneCheck = Join-Path $state "done-check.json"
$prompt = Join-Path $state "PROMPT.md"

# ---- locate binaries ----
if (-not $PhoenixBin) {
  $cand = @("$repo\target\release\phoenix-mcp.exe","$repo\target\debug\phoenix-mcp.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($cand) { $PhoenixBin = $cand } elseif (Get-Command phoenix-mcp -ErrorAction SilentlyContinue) { $PhoenixBin = "phoenix-mcp" }
}
if (-not $PhoenixBin) { Die "phoenix-mcp not found. Build it (cargo build --release) or pass -PhoenixBin." }
if (-not $Copilot) {
  if (Test-Path "$env:APPDATA\npm\copilot.cmd") { $Copilot = "$env:APPDATA\npm\copilot.cmd" } elseif (Get-Command copilot -ErrorAction SilentlyContinue) { $Copilot = "copilot" }
}
if (-not $Copilot) { Die "copilot CLI not found. Install it or pass -Copilot." }

# ---- validate state ----
if (-not (Test-Path $doneCheck)) { Die "missing $doneCheck (the top-level acceptance check)." }
if (-not (Test-Path $prompt))    { Die "missing $prompt (the fixed per-loop instructions)." }
$env:PHOENIX_WORKSPACE = $repo
# Pass the check by @file (not inline JSON) — avoids PowerShell→exe quote-mangling.
$doneArg = "@$doneCheck"

# ---- baseline: the done-check should start RED so completion can be proven failure-first ----
Info "binaries: phoenix=$PhoenixBin  copilot=$Copilot"
Info "baseline sense of done-check..."
& $PhoenixBin sense $doneArg | Out-Null
$baselineGreen = ($LASTEXITCODE -eq 0)
if ($baselineGreen -and -not $AllowPreGreen) {
  Die "done-check is ALREADY GREEN at start -- it can't prove failure-first (it'd be a vacuous gate). Re-target the check at the real unmet goal, or pass -AllowPreGreen if it's legitimately satisfied."
}

# ---- the loop ----
$start = Get-Date
$noProgress = 0
$lastSig = ""
$loop = 0
$traceFile = Join-Path $repo ".phoenix\trace.jsonl"
$backlog = Join-Path $state "backlog.json"

while ($loop -lt $MaxLoops) {
  $loop++
  if (((Get-Date) - $start).TotalMinutes -ge $MaxMinutes) { Warn "wall-clock budget ($MaxMinutes min) reached."; break }

  # 1. DRIVER decides done: is the done-check failure-first satisfied on an intact trace?
  & $PhoenixBin accept $doneArg 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { Info "done-check ACCEPTED (failure-first, green). Goal proven complete."; break }

  # 2. Fresh-context agent turn (Huntley: one task per loop, brain on disk).
  Info "iteration $loop/$MaxLoops -- invoking agent (fresh context)..."
  $flat = (Get-Content $prompt -Raw) -replace "`r?`n", " "
  & $Copilot -p $flat --allow-all-tools --allow-all-paths --add-dir $repo
  if ($LASTEXITCODE -ne 0) { Warn "copilot exited $LASTEXITCODE." }

  # 3. Trace must stay intact (tamper-evidence). A broken chain means we can't trust completion.
  & $PhoenixBin verify-trace 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) { Die "trace chain BROKEN after iteration $loop -- stopping (possible tampering/corruption)." }

  # 4. No-progress detection: hash trace + backlog. Unchanged N times in a row => stuck.
  $sig = (FileSig $traceFile) + "|" + (FileSig $backlog)
  if ($sig -eq $lastSig) { $noProgress++; Warn "no state change ($noProgress/$NoProgressStop)." } else { $noProgress = 0 }
  $lastSig = $sig
  if ($noProgress -ge $NoProgressStop) { Warn "no progress for $NoProgressStop iterations -- stopping (stuck; this is a planning problem)."; break }
}

# ---- completion: DRIVER writes the proof bundle + tag (never the agent) ----
$acc = & $PhoenixBin accept $doneArg 2>$null
if ($LASTEXITCODE -eq 0) {
  $proof = [ordered]@{
    completed_at   = (Get-Date).ToString("o")
    iterations     = $loop
    accept         = ($acc | ConvertFrom-Json)
    trace_sha256   = (FileSig $traceFile)
    backlog_sha256 = (FileSig $backlog)
  }
  $proof | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $state "completed.json")
  Info "COMPLETE in $loop iterations. Proof -> $Dir\completed.json"
  if (-not $NoTag -and (Test-Path "$repo\.git")) {
    # Tagging is best-effort: a proven completion must not be undone by a tag failure
    # (e.g. a repo with no commits yet). Never let this flip the success exit code.
    try {
      $tag = "phoenix-ralph-$((Get-Date).ToString('yyyyMMdd-HHmmss'))"
      & git -C $repo tag -a $tag -m "phoenix-ralph: done-check proven failure-first ($loop iterations)" 2>$null
      if ($LASTEXITCODE -eq 0) { Info "git tag: $tag" } else { Warn "tag skipped (git exit $LASTEXITCODE; needs at least one commit)." }
    } catch { Warn "tag skipped: $_" }
  }
  exit 0
} else {
  Warn "stopped WITHOUT proving the done-check ($loop iterations). Latest accept verdict:"
  Write-Host $acc
  exit 1
}
