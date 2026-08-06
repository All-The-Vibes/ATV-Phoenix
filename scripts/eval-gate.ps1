# scripts/eval-gate.ps1 -- Tier 3 auto-merge gate. Exit 0=pass, 1=regression, 2=error/needs-human.
#
# Scope is DERIVED from the changed-file set, not asserted by the caller (issue #163). A caller that
# gets to declare the gate inapplicable is making a claim; LAW 0 wants evidence. Classification is
# fail-closed: a path matching neither list is treated as scored, so a new directory is measured by
# default rather than exempted by omission.
param(
  [switch]$Exempt,
  [string]$ResultsOut = (Join-Path $env:TEMP "eval-gate-$(Get-Random).jsonl"),
  [string]$PrebuiltResults = "",
  [string]$ChangedFiles = "",
  [string]$BaseRef = "origin/main"
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$scoreboard = Join-Path $repoRoot "eval\scoreboard.json"

# Files that define the gate itself. Measuring a change to the meter with the meter is circular, and
# exempting it would let a gate-disabling edit through unmeasured. Neither is acceptable, so route to
# a human via exit 2, which charter STEP 7 already handles as "leave as draft, notify Maverick".
$gateOwning = @(
  'scripts/eval-gate.ps1',
  'scripts/update-scoreboard.ps1',
  'eval/scoreboard.json'
)

function Test-UnscoredPath($p) {
  # Off the Arm B measured path. skills/** is deliberately NOT here: skills are the agent's
  # instructions and are the change most likely to move the resolved rate.
  if ($p -like 'skills/*') { return $false }
  if ($p -like 'docs/*' -or $p -like 'tests/*' -or $p -like 'issues/*' -or $p -like '.github/*') { return $true }
  if ($p -like 'scripts/*') { return $true }
  if ($p -like '*.md') { return $true }
  return $false
}

function Get-GateScope($files) {
  $scored = @(); $unscored = @(); $gate = @()
  foreach ($f in $files) {
    $p = ($f -replace '\\', '/').Trim()
    if (-not $p) { continue }
    if ($gateOwning -contains $p) { $gate += $p }
    elseif (Test-UnscoredPath $p) { $unscored += $p }
    else { $scored += $p }
  }
  return @{ scored = $scored; unscored = $unscored; gate = $gate }
}

if ($Exempt.IsPresent) {
  Write-Output "[eval-gate] EXEMPT: waiver ASSERTED by caller (not derived) -- tier 3 waived"
  exit 0
}

# Derive scope. An explicit -ChangedFiles wins; otherwise ask git.
$fileList = @()
if ($ChangedFiles) {
  $fileList = ($ChangedFiles -split '[,\r\n]') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}
else {
  try {
    $fileList = @(& git -C $repoRoot diff --name-only "$BaseRef...HEAD" 2>$null | Where-Object { $_ })
  }
  catch { $fileList = @() }
}

if ($fileList.Count -gt 0) {
  $scope = Get-GateScope $fileList
  Write-Output "[eval-gate] scope: $($scope.scored.Count) scored, $($scope.unscored.Count) unscored, $($scope.gate.Count) gate-owning (of $($fileList.Count) changed)"
  if ($scope.gate.Count -gt 0) {
    Write-Output "[eval-gate] NEEDS-HUMAN: changes the gate itself -- $($scope.gate -join ', ')"
    exit 2
  }
  if ($scope.scored.Count -eq 0) {
    Write-Output "[eval-gate] AUTO-EXEMPT: no changed file is on the scored path -- tier 3 cannot move"
    $scope.unscored | ForEach-Object { Write-Output "[eval-gate]   unscored: $_" }
    exit 0
  }
  $scope.scored | ForEach-Object { Write-Output "[eval-gate]   scored: $_" }
}
else {
  Write-Output "[eval-gate] scope: no changed-file set available -- running the eval (fail closed)"
}

if (-not (Test-Path $scoreboard)) {
  Write-Host "[eval-gate] ERROR: eval/scoreboard.json not found"; exit 2
  exit 2
}

$rawBytes = [System.IO.File]::ReadAllBytes($scoreboard)
if ($rawBytes[0] -eq 0xEF) { $rawBytes = $rawBytes[3..($rawBytes.Length-1)] }
$board = [System.Text.Encoding]::UTF8.GetString($rawBytes) | ConvertFrom-Json
$baselineB = $board.baseline.swe_bench_lite.arm_b_phoenix_resolved
Write-Output "[eval-gate] Baseline Arm B: $baselineB"

if ($PrebuiltResults -and (Test-Path $PrebuiltResults)) {
  Write-Output "[eval-gate] Using pre-built results (test mode)"
  Copy-Item $PrebuiltResults $ResultsOut -Force
} else {
  $runSwe = Join-Path $repoRoot "evals\swe-bench-lite\run_swe.ps1"
  if (-not (Test-Path $runSwe)) { Write-Error "[eval-gate] ERROR: run_swe.ps1 not found"; exit 2 }
  Write-Output "[eval-gate] Running swe-bench-lite..."
  powershell -NoProfile -ExecutionPolicy Bypass -File $runSwe -OutFile $ResultsOut 2>&1
  if (-not (Test-Path $ResultsOut)) { Write-Error "[eval-gate] ERROR: no results produced"; exit 2 }
}

$rows = Get-Content $ResultsOut | ForEach-Object { $_ | ConvertFrom-Json }
$armB = $rows | Where-Object { $_.arm -eq "B_phoenix" }
if ($armB.Count -eq 0) { Write-Error "[eval-gate] ERROR: no B_phoenix rows"; exit 2 }
$scoreB = [math]::Round(($armB | Where-Object { $_.resolved -eq 1 }).Count / $armB.Count, 4)
$delta = [math]::Round($scoreB - $baselineB, 4)
Write-Output "[eval-gate] Arm B score: $scoreB (baseline: $baselineB delta: $delta)"

$updater = Join-Path $PSScriptRoot "update-scoreboard.ps1"
if (Test-Path $updater) {
  powershell -NoProfile -ExecutionPolicy Bypass -File $updater -ResultsFile $ResultsOut -Trigger pr 2>&1 | Out-Null
}

if ($delta -lt 0) {
  Write-Warning "[eval-gate] REGRESSION: Arm B $scoreB < baseline $baselineB (delta $delta)"
  exit 1
}
Write-Output "[eval-gate] PASS: Arm B $scoreB >= baseline $baselineB"
exit 0
