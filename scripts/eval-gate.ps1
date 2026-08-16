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
  # Off the Arm B measured path.
  if ($p -like 'skills/*') { return $false }
  if ($p -like 'docs/*' -or $p -like 'tests/*' -or $p -like 'issues/*' -or $p -like '.github/*') { return $true }
  if ($p -like 'scripts/*') { return $true }
  if ($p -like '*.md') { return $true }
  return $false
}

function Get-BaselineArmB {
  if (-not (Test-Path $scoreboard)) { return $null }
  try {
    $bytes = [System.IO.File]::ReadAllBytes($scoreboard)
    if ($bytes[0] -eq 0xEF) { $bytes = $bytes[3..($bytes.Length - 1)] }
    return ([System.Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json).baseline.swe_bench_lite.arm_b_phoenix_resolved
  }
  catch { return $null }
}

function Get-GateScope($files) {
  $scored = @(); $unscored = @(); $gate = @(); $behaviour = @()
  foreach ($f in $files) {
    $p = ($f -replace '\\', '/').Trim()
    if (-not $p) { continue }
    if ($gateOwning -contains $p) { $gate += $p }
    elseif ($p -like 'skills/*') { $behaviour += $p }
    elseif (Test-UnscoredPath $p) { $unscored += $p }
    else { $scored += $p }
  }
  return @{ scored = $scored; unscored = $unscored; gate = $gate; behaviour = $behaviour }
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
  Write-Output "[eval-gate] scope: $($scope.scored.Count) scored, $($scope.behaviour.Count) behaviour, $($scope.unscored.Count) unscored, $($scope.gate.Count) gate-owning (of $($fileList.Count) changed)"
  if ($scope.gate.Count -gt 0) {
    Write-Output "[eval-gate] NEEDS-HUMAN: changes the gate itself -- $($scope.gate -join ', ')"
    exit 2
  }

  # skills/** changes agent behaviour and belongs on the scored path in principle. Whether it is
  # worth blocking on depends entirely on whether the meter can discriminate. A resolved-rate cannot
  # exceed 1.0, so at a saturated baseline the eval can only ever report a tie or a flake, and with
  # n=9 a single stochastic failure reads as a regression. Blocking a skill PR on that buys friction
  # and no safety, and a gate that fires wrongly gets routed around. Disclose instead, and let the
  # classification tighten by itself once the baseline is fixed. Tracked in #142.
  $unmeasured = $false
  if ($scope.behaviour.Count -gt 0) {
    $baselineNow = Get-BaselineArmB
    if ($null -ne $baselineNow -and $baselineNow -ge 1.0) {
      Write-Output "[eval-gate] UNMEASURED: $($scope.behaviour.Count) skill file(s) change agent behaviour and should be scored, but the baseline is $baselineNow, the highest a resolved-rate can reach. Tier 3 cannot discriminate an improvement from a tie here, so this is disclosed and NOT blocking. Tracked in issue #142."
      $scope.behaviour | ForEach-Object { Write-Output "[eval-gate]   unmeasured: $_" }
      $unmeasured = $true
    }
    else {
      Write-Output "[eval-gate] baseline $baselineNow is below the ceiling -- skill changes are scored"
      $scope.scored += $scope.behaviour
    }
  }

  if ($scope.scored.Count -eq 0) {
    if ($unmeasured) {
      Write-Output "[eval-gate] PASS (unmeasured): nothing on the scored path, skill changes disclosed above and not blocked"
    }
    else {
      Write-Output "[eval-gate] AUTO-EXEMPT: no changed file is on the scored path -- tier 3 cannot move"
      $scope.unscored | ForEach-Object { Write-Output "[eval-gate]   unscored: $_" }
    }
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

# Gate-instrument validity (MISSION.md, issue #171). A shipping gate counts only while its
# instrument can still discriminate: a measurement that is missing, void, older than 14 days,
# or saturated at a perfect score is UNKNOWN. The charter has said so since 2026-08-07 and
# nothing enforced the age half, so every merge was gated against whatever the baseline
# happened to be, however old. A gate blind to the age of its own instrument cannot be the
# thing that decides whether the loop is shipping blind.
#
# UNKNOWN discloses and does not block, deliberately. Failing here would stop the very pull
# requests that could refresh the baseline, which is the deadlock this rule exists to avoid.
$maxBaselineAgeDays = 14
$baselineValid = $board.baseline.swe_bench_lite.valid
if ($null -ne $baselineValid -and -not $baselineValid) {
  Write-Output "[eval-gate] UNKNOWN: the baseline measurement is marked void, so Tier 3 cannot discriminate. It neither blocks nor passes silently. Tracked in issue #171."
}
$baselineDateRaw = $board.baseline.date
if ($baselineDateRaw) {
  $parsedDate = [datetime]::MinValue
  if ([datetime]::TryParse($baselineDateRaw, [ref]$parsedDate)) {
    $ageDays = [int]((Get-Date).Date - $parsedDate.Date).TotalDays
    if ($ageDays -gt $maxBaselineAgeDays) {
      Write-Output "[eval-gate] UNKNOWN: the baseline was measured $ageDays days ago ($baselineDateRaw), past the $maxBaselineAgeDays-day window in MISSION.md. Tier 3 is gating against a measurement that can no longer discriminate; this is disclosed, not blocked, because blocking would stop the changes that could refresh it. Tracked in issue #171."
    }
  }
  else {
    Write-Output "[eval-gate] UNKNOWN: the baseline date '$baselineDateRaw' could not be parsed, so its age cannot be checked. Tracked in issue #171."
  }
}
else {
  Write-Output "[eval-gate] UNKNOWN: the baseline carries no date, so its age cannot be checked. Tracked in issue #171."
}

if ($baselineB -ge 1.0) {
  Write-Output "[eval-gate] SATURATED: the baseline is $baselineB, which is the highest a resolved-rate can reach. This gate can detect a regression and cannot detect an improvement, so a tie at $baselineB is not evidence that the harness got better. Tracked in issue #142."
}

# Re-enter this same interpreter rather than the name `powershell`, which does not exist on
# Linux or macOS (they ship `pwsh`). Hardcoding it made the gate unrunnable off Windows, which
# stayed invisible while nothing exercised it on a Linux runner.
$psExe = (Get-Process -Id $PID).Path
if (-not $psExe) { $psExe = "powershell" }

if ($PrebuiltResults -and (Test-Path $PrebuiltResults)) {
  Write-Output "[eval-gate] Using pre-built results (test mode)"
  Copy-Item $PrebuiltResults $ResultsOut -Force
} else {
  $runSwe = Join-Path $repoRoot "evals\swe-bench-lite\run_swe.ps1"
  if (-not (Test-Path $runSwe)) { Write-Error "[eval-gate] ERROR: run_swe.ps1 not found"; exit 2 }
  Write-Output "[eval-gate] Running swe-bench-lite..."
  & $psExe -NoProfile -ExecutionPolicy Bypass -File $runSwe -OutFile $ResultsOut 2>&1
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
  & $psExe -NoProfile -ExecutionPolicy Bypass -File $updater -ResultsFile $ResultsOut -Trigger pr 2>&1 | Out-Null
}

if ($delta -lt 0) {
  Write-Warning "[eval-gate] REGRESSION: Arm B $scoreB < baseline $baselineB (delta $delta)"
  exit 1
}
Write-Output "[eval-gate] PASS: Arm B $scoreB >= baseline $baselineB"
exit 0
