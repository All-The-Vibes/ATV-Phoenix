#requires -Version 5
<#
.SYNOPSIS
  ATV-Phoenix Intent driver — orchestrate N /goal loops from a single intent manifest,
  proven complete via composite phoenix_accept (ALL goals failure-first satisfied).

.DESCRIPTION
  phoenix-intent sits above phoenix-ralph: it reads an intent manifest (intent.json),
  validates all goal checks start RED (baseline enforcement), executes each goal via its
  own phoenix-ralph loop (with a per-goal PHOENIX_WORKSPACE), then proves composite
  completion with `phoenix-mcp intent-accept`.

  The DRIVER decides composite completion — not the agent. The composite gate is satisfied
  only when ALL N goals are individually proven failure-first (saw_red + green_after_red +
  currently_green) on intact per-goal tamper-evident traces.

  Execution order:
    - Goals with empty depends_on[] are independent and may run sequentially in this
      driver (v1: sequential for simplicity; v2 can parallelize via jobs).
    - Goals with non-empty depends_on[] wait for their dependencies to be proven before
      they start.

  Per-goal state layout (.phoenix-intent/<goal_id>/):
    .phoenix/trace.jsonl   per-goal tamper-evident trace (PHOENIX_WORKSPACE for this goal)
    PROMPT.md              goal-specific ralph prompt
    backlog.json           goal backlog
    done-check.json        the goal's acceptance check (matches intent.json check)
    completed.json         written by ralph on success

  Top-level state layout (.phoenix-intent/):
    intent.json            the intent manifest (source of truth)
    completed.json         written by THIS driver on composite success (proof bundle)

.PARAMETER IntentFile
  Path to the intent manifest JSON. Defaults to .phoenix-intent/intent.json.

.PARAMETER MaxLoopsPerGoal
  Maximum ralph loop iterations per goal (passed to phoenix-ralph -MaxLoops). Default 50.

.PARAMETER MaxMinutesPerGoal
  Wall-clock budget per goal in minutes (passed to phoenix-ralph -MaxMinutes). Default 60.

.PARAMETER PhoenixBin
  Path to phoenix-mcp binary. Auto-detected if absent.

.PARAMETER Copilot
  Path to copilot CLI. Auto-detected if absent.

.PARAMETER AllowPreGreen
  Pass through to ralph: allow a goal's done-check to already be green at baseline.
  NOT recommended — a pre-green check is a vacuous gate.

.NOTES
  Windows PS5.1 guard: self-promotes to pwsh (same as phoenix-ralph).
#>

# ---- Windows PS5.1 guard: self-promote to pwsh ----
if ($PSVersionTable.PSVersion.Major -lt 6) {
  if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    Write-Host "[intent] FATAL: phoenix-intent requires PowerShell 7+ on Windows." -ForegroundColor Red
    Write-Host "[intent]        Install PowerShell 7: https://aka.ms/powershell" -ForegroundColor Red
    exit 2
  }
  & pwsh -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath @args
  exit $LASTEXITCODE
}
$PSNativeCommandArgumentPassing = 'Standard'

[CmdletBinding()]
param(
  [string]$IntentFile    = ".phoenix-intent/intent.json",
  [int]$MaxLoopsPerGoal  = 50,
  [int]$MaxMinutesPerGoal = 60,
  [string]$PhoenixBin    = "",
  [string]$Copilot       = "",
  [switch]$AllowPreGreen
)

$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "[intent] $m" -ForegroundColor Cyan }
function Warn($m){ Write-Host "[intent] $m" -ForegroundColor Yellow }
function Die($m) { Write-Host "[intent] FATAL: $m" -ForegroundColor Red; exit 2 }

$repo        = (Get-Location).Path
$intentPath  = Join-Path $repo $IntentFile
$intentDir   = Join-Path $repo ".phoenix-intent"

# ---- locate binaries ----
if (-not $PhoenixBin) {
  $cand = @(
    "$repo\target\release\phoenix-mcp.exe",
    "$repo\target\debug\phoenix-mcp.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($cand)                                           { $PhoenixBin = $cand }
  elseif (Get-Command phoenix-mcp -ErrorAction SilentlyContinue) { $PhoenixBin = "phoenix-mcp" }
}
if (-not $PhoenixBin) { Die "phoenix-mcp not found. Build it (cargo build --release) or pass -PhoenixBin." }

if (-not $Copilot) {
  if (Test-Path "$env:APPDATA\npm\copilot.cmd") { $Copilot = "$env:APPDATA\npm\copilot.cmd" }
  elseif (Get-Command copilot -ErrorAction SilentlyContinue) { $Copilot = "copilot" }
}
if (-not $Copilot) { Die "copilot CLI not found. Install it or pass -Copilot." }

# ---- locate ralph driver (same directory as this script, or repo dist/ralph/) ----
$ralphScript = Join-Path (Split-Path $PSCommandPath) "..\ralph\phoenix-ralph.ps1"
if (-not (Test-Path $ralphScript)) {
  $ralphScript = Join-Path $repo "dist\ralph\phoenix-ralph.ps1"
}
if (-not (Test-Path $ralphScript)) { Die "phoenix-ralph.ps1 not found near $PSCommandPath or at dist/ralph/." }

# ---- validate manifest ----
if (-not (Test-Path $intentPath)) { Die "intent manifest not found: $intentPath" }
$manifest = Get-Content $intentPath -Raw | ConvertFrom-Json
if (-not $manifest.intent) { Die "intent manifest missing 'intent' field." }
if (-not $manifest.goals -or $manifest.goals.Count -eq 0) { Die "intent manifest has no goals." }
if ($manifest.goals.Count -gt 5) {
  Die ("intent has {0} goals — exceeds the ceiling of 5. Split into multiple intents." -f $manifest.goals.Count)
}

Info "intent: $($manifest.intent)"
Info "goals ($($manifest.goals.Count)): $($manifest.goals.id -join ', ')"

# ---- validate goal ids are unique ----
$goalIds = $manifest.goals | ForEach-Object { $_.id }
$dupes = $goalIds | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name }
if ($dupes) { Die "duplicate goal ids: $($dupes -join ', ')" }

# ---- validate depends_on references exist ----
foreach ($goal in $manifest.goals) {
  if ($goal.depends_on) {
    foreach ($dep in $goal.depends_on) {
      if ($dep -notin $goalIds) { Die "goal '$($goal.id)' depends_on unknown goal '$dep'" }
    }
  }
}

# ---- BASELINE: all goal checks must start RED ----
Info "baseline: verifying all goal checks start RED..."
$env:PHOENIX_WORKSPACE = $repo
$anyPreGreen = $false
foreach ($goal in $manifest.goals) {
  $checkJson = $goal.check | ConvertTo-Json -Compress -Depth 5
  $tmpCheck = [System.IO.Path]::GetTempFileName() + ".json"
  try {
    [System.IO.File]::WriteAllText($tmpCheck, $checkJson, [System.Text.Encoding]::UTF8)
    & $PhoenixBin sense "@$tmpCheck" 2>$null | Out-Null
    $isGreen = ($LASTEXITCODE -eq 0)
  } finally {
    Remove-Item $tmpCheck -ErrorAction SilentlyContinue
  }
  if ($isGreen) {
    if ($AllowPreGreen) {
      Warn "goal '$($goal.id)' check is already GREEN at baseline (--AllowPreGreen set; continuing)."
      $anyPreGreen = $true
    } else {
      Die ("goal '$($goal.id)' check is ALREADY GREEN at baseline — it cannot prove failure-first " +
           "(vacuous gate). Re-target the check at the real unmet goal, or pass -AllowPreGreen.")
    }
  } else {
    Info "  [RED] goal '$($goal.id)' — ok, baseline confirmed red."
  }
}
if ($anyPreGreen) {
  Warn "WARNING: one or more goal checks were pre-green. Composite proof will be weaker."
}

# ---- topological sort (Kahn's algorithm) for execution order ----
function Get-ExecutionOrder($goals) {
  $inDegree = @{}
  $adj      = @{}
  foreach ($g in $goals) {
    $inDegree[$g.id] = 0
    $adj[$g.id]      = @()
  }
  foreach ($g in $goals) {
    foreach ($dep in @($g.depends_on)) {
      if ($dep) { $adj[$dep] += $g.id; $inDegree[$g.id]++ }
    }
  }
  $queue  = [System.Collections.Generic.Queue[string]]::new()
  $order  = [System.Collections.Generic.List[string]]::new()
  foreach ($id in $inDegree.Keys) { if ($inDegree[$id] -eq 0) { $queue.Enqueue($id) } }
  while ($queue.Count -gt 0) {
    $cur = $queue.Dequeue()
    $order.Add($cur)
    foreach ($nxt in $adj[$cur]) {
      $inDegree[$nxt]--
      if ($inDegree[$nxt] -eq 0) { $queue.Enqueue($nxt) }
    }
  }
  if ($order.Count -ne $goals.Count) { Die "dependency cycle detected in intent goals." }
  return $order
}

$execOrder = Get-ExecutionOrder $manifest.goals
Info "execution order: $($execOrder -join ' → ')"

# ---- EXECUTE each goal via phoenix-ralph ----
$goalMap = @{}
foreach ($g in $manifest.goals) { $goalMap[$g.id] = $g }

$start     = Get-Date
$succeeded = @()
$failed    = @()

foreach ($goalId in $execOrder) {
  $goal    = $goalMap[$goalId]
  $goalWs  = Join-Path $intentDir $goalId
  $goalDoneCheck = Join-Path $goalWs "done-check.json"
  $goalPrompt    = Join-Path $goalWs "PROMPT.md"

  Info ""
  Info "=== goal: $goalId — $($goal.title) ==="

  # ---- check dependencies are proven ----
  foreach ($dep in @($goal.depends_on)) {
    if ($dep -and $dep -notin $succeeded) {
      Warn "dependency '$dep' was not proven — skipping goal '$goalId'."
      $failed += $goalId
      continue
    }
  }
  if ($goalId -in $failed) { continue }

  # ---- scaffold goal state dir if missing ----
  if (-not (Test-Path $goalWs)) { New-Item -ItemType Directory -Path $goalWs -Force | Out-Null }
  New-Item -ItemType Directory -Path (Join-Path $goalWs ".phoenix") -Force -ErrorAction SilentlyContinue | Out-Null

  # ---- write done-check.json (sync from manifest so they stay aligned) ----
  $goal.check | ConvertTo-Json -Depth 5 | Set-Content $goalDoneCheck -Encoding UTF8

  # ---- write a minimal PROMPT.md if one doesn't exist yet ----
  if (-not (Test-Path $goalPrompt)) {
    @"
# Goal: $($goal.title)

Intent: $($manifest.intent)

Goal id: $goalId
Done-check: see done-check.json

Work the backlog (backlog.json) until the done-check is green.
Use phoenix_sense to test each step. Use phoenix_snapshot before risky edits.
Do NOT mark done until phoenix_accept confirms the done-check is failure-first satisfied.
"@ | Set-Content $goalPrompt -Encoding UTF8
    Info "  wrote default PROMPT.md for goal '$goalId' (edit before running for real)."
  }

  # ---- run per-goal ralph loop ----
  $env:PHOENIX_WORKSPACE = $goalWs
  $ralphArgs = @(
    "-Dir", ".",
    "-MaxLoops", $MaxLoopsPerGoal,
    "-MaxMinutes", $MaxMinutesPerGoal,
    "-PhoenixBin", $PhoenixBin,
    "-Copilot", $Copilot
  )
  if ($AllowPreGreen) { $ralphArgs += "-AllowPreGreen" }

  Info "  running ralph for goal '$goalId' (workspace=$goalWs)..."
  & pwsh -NoProfile -ExecutionPolicy Bypass -File $ralphScript @ralphArgs
  $ralphExit = $LASTEXITCODE
  $env:PHOENIX_WORKSPACE = $repo

  if ($ralphExit -eq 0) {
    Info "  goal '$goalId' PROVEN by ralph."
    $succeeded += $goalId
  } else {
    Warn "  goal '$goalId' NOT proven by ralph (exit $ralphExit)."
    $failed += $goalId
  }
}

# ---- COMPOSITE PROOF ----
Info ""
Info "=== composite accept ==="
$intentArg = $IntentFile
$compositeJson = & $PhoenixBin intent-accept $intentArg 2>$null
$compositeExit = $LASTEXITCODE

if ($compositeJson) {
  Write-Host $compositeJson
}

if ($compositeExit -eq 0) {
  $elapsed = [math]::Round(((Get-Date) - $start).TotalMinutes, 1)
  Info ""
  Info "COMPOSITE COMPLETE in ${elapsed}min. All $($manifest.goals.Count) goal(s) proven failure-first."

  # ---- write proof bundle ----
  $proof = [ordered]@{
    completed_at  = (Get-Date).ToString("o")
    intent        = $manifest.intent
    goal_count    = $manifest.goals.Count
    goals_proven  = $succeeded
    elapsed_min   = $elapsed
    composite     = ($compositeJson | ConvertFrom-Json)
  }
  $proof | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $intentDir "completed.json") -Encoding UTF8
  Info "Proof bundle → .phoenix-intent/completed.json"

  if (Test-Path "$repo\.git") {
    try {
      $tag = "phoenix-intent-$((Get-Date).ToString('yyyyMMdd-HHmmss'))"
      & git -C $repo tag -a $tag -m "phoenix-intent: composite done-check proven ($($manifest.goals.Count) goals)" 2>$null
      if ($LASTEXITCODE -eq 0) { Info "git tag: $tag" } else { Warn "tag skipped (git exit $LASTEXITCODE)." }
    } catch { Warn "tag skipped: $_" }
  }
  exit 0
} else {
  Warn "Composite accept FAILED. Not all goals were proven."
  if ($failed.Count -gt 0) { Warn "Goals that did not complete: $($failed -join ', ')" }
  exit 1
}
