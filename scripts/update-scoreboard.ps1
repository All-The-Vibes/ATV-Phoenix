# scripts/update-scoreboard.ps1
param(
  [string]$ResultsFile = "evals\swe-bench-lite\results.jsonl",
  [string]$ScoreboardFile = "eval\scoreboard.json",
  [string]$Trigger = "pr",
  [string]$PR = "",
  [string]$Model = "GitHub Copilot CLI"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $ResultsFile)) { Write-Error "Results file not found: $ResultsFile"; exit 2 }
if (-not (Test-Path $ScoreboardFile)) { Write-Error "Scoreboard not found: $ScoreboardFile"; exit 2 }
$rows = Get-Content $ResultsFile | ForEach-Object { $_ | ConvertFrom-Json }
$armA = $rows | Where-Object { $_.arm -eq "A_vanilla" }
$armB = $rows | Where-Object { $_.arm -eq "B_phoenix" }
$rA = if ($armA.Count -gt 0) { [math]::Round(($armA | Where-Object { $_.resolved -eq 1 }).Count / $armA.Count, 4) } else { 0 }
$rB = if ($armB.Count -gt 0) { [math]::Round(($armB | Where-Object { $_.resolved -eq 1 }).Count / $armB.Count, 4) } else { 0 }
$tasks = [math]::Max($armA.Count, $armB.Count)
$rawBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $ScoreboardFile).Path)
# Strip BOM if present
if ($rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF) { $rawBytes = $rawBytes[3..($rawBytes.Length-1)] }
$board = [System.Text.Encoding]::UTF8.GetString($rawBytes) | ConvertFrom-Json
$baseB = $board.baseline.swe_bench_lite.arm_b_phoenix_resolved
$baseA = $board.baseline.swe_bench_lite.arm_a_vanilla_resolved
$deltaB = [math]::Round($rB - $baseB, 4)
$sha = try { git rev-parse HEAD 2>$null } catch { "unknown" }; if (-not $sha) { $sha = "unknown" }
$today = (Get-Date).ToString("yyyy-MM-dd")
$run = [ordered]@{ date=$today; commit=$sha; trigger=$Trigger; tier="lite"; arm_a_vanilla_resolved=$rA; arm_b_phoenix_resolved=$rB; delta_b_from_baseline=$deltaB; tasks=$tasks; model=$Model; reps=1; pr=if($PR){$PR}else{$null} }
$board.runs += $run
$json = $board | ConvertTo-Json -Depth 10
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText((Resolve-Path $ScoreboardFile).Path, $json, $utf8NoBom)

# Rewrite README Score Tracker section
$readmePath = if (Test-Path "README.md") { (Resolve-Path "README.md").Path } else { $null }
if ($readmePath) {
  $deltaSymB = if ($deltaB -ge 0) { "+$deltaB" } else { "WARN:$deltaB" }
  $lines = @(
    "## Score Tracker"
    ""
    "| Tier | Arm | Resolved | Baseline | Delta | Date |"
    "| ---- | --- | -------- | -------- | ----- | ---- |"
    "| swe-bench-lite (local, $tasks tasks) | **B Phoenix** | **$rB** | $baseB | $deltaSymB | $today |"
    "| swe-bench-lite (local, $tasks tasks) | A Vanilla | $rA | $baseA | -- | $today |"
    "| SWE-bench Verified 500 (Azure) | B Phoenix | -- | -- | -- | *not yet run* |"
    ""
    "_Score gate: implementation PRs must hold or beat Arm B baseline ($baseB). Docs/test-only PRs exempt._"
    ""
  )
  $newSection = $lines -join "`n"
  $rawR = [System.IO.File]::ReadAllBytes($readmePath)
  if ($rawR[0] -eq 0xEF) { $rawR = $rawR[3..($rawR.Length-1)] }
  $readme = [System.Text.Encoding]::UTF8.GetString($rawR)
  if ($readme -match "(?s)## Score Tracker.*?(?=\n## |\z)") {
    $readme = $readme -replace "(?s)## Score Tracker.*?(?=\n## |\z)", ($newSection)
  } else {
    $first = $readme.IndexOf("`n")
    $readme = $readme.Substring(0, $first+1) + "`n" + $newSection + $readme.Substring($first+1)
  }
  [System.IO.File]::WriteAllText($readmePath, $readme, $utf8NoBom)
  Write-Output "README updated"
}
Write-Output "Arm B: $rB (baseline: $baseB delta: $deltaB)"
if ($deltaB -lt 0) { Write-Warning "REGRESSION: Arm B dropped $([math]::Abs($deltaB))"; exit 1 }
exit 0