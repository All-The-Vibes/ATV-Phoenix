# scripts/eval-gate.ps1 -- Tier 3 auto-merge gate. Exit 0=pass, 1=regression, 2=error.
param(
  [switch]$Exempt,
  [string]$ResultsOut = (Join-Path $env:TEMP "eval-gate-$(Get-Random).jsonl"),
  [string]$PrebuiltResults = ""
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$scoreboard = Join-Path $repoRoot "eval\scoreboard.json"

if ($Exempt.IsPresent) {
  Write-Output "[eval-gate] EXEMPT: docs/test-only PR -- tier 3 waived"
  exit 0
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
  powershell -ExecutionPolicy Bypass -File $runSwe -OutFile $ResultsOut -Append:$false 2>&1
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
  powershell -ExecutionPolicy Bypass -File $updater -ResultsFile $ResultsOut -Trigger pr 2>&1 | Out-Null
}

if ($delta -lt 0) {
  Write-Warning "[eval-gate] REGRESSION: Arm B $scoreB < baseline $baselineB (delta $delta)"
  exit 1
}
Write-Output "[eval-gate] PASS: Arm B $scoreB >= baseline $baselineB"
exit 0
