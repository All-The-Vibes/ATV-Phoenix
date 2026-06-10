# SWE-bench-style lite benchmark for ATV-Phoenix.
# Methodology = the SWE-bench evaluation contract:
#   a task is RESOLVED iff, after the agent's fix, ALL FAIL_TO_PASS tests pass
#   AND ALL PASS_TO_PASS tests still pass (no regressions).
# Two arms, same tasks: A_vanilla (Copilot self-judges) vs B_phoenix (verify-heal loop enforced).
# Reports resolved-rate per arm. Writes results.jsonl incrementally.
param(
  [int]$Reps = 1,
  [string]$Filter = "*",      # wildcard on task folder name (e.g. "hard-*")
  [string]$OutFile = "",       # results file; default results.jsonl
  [switch]$Append              # keep existing results instead of truncating
)

$ErrorActionPreference = "Continue"
$root    = "C:\Users\shyamsridhar\code\ATV-Phoenix\evals\swe-bench-lite"
$taskdir = "$root\tasks"
$cop     = "$env:APPDATA\npm\copilot.cmd"
$results = if ($OutFile) { $OutFile } else { "$root\results.jsonl" }

function New-Instance($task) {
  # Fresh working copy with ONLY solution.py + problem.md visible to the agent (tests are hidden).
  $dir = Join-Path $env:TEMP ("swe_" + $task.Name + "_" + [guid]::NewGuid().ToString("N").Substring(0,6))
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  Copy-Item "$($task.FullName)\solution.py" "$dir\solution.py" -Force
  Copy-Item "$($task.FullName)\problem.md" "$dir\problem.md" -Force
  return $dir
}

function Score($dir, $task) {
  # Bring in the hidden tests and apply the resolved contract.
  Copy-Item "$($task.FullName)\test_f2p.py" "$dir\test_f2p.py" -Force
  Copy-Item "$($task.FullName)\test_p2p.py" "$dir\test_p2p.py" -Force
  Push-Location $dir
  python -m pytest test_f2p.py -q *> "$dir\_f2p.txt"; $f2p = $LASTEXITCODE
  python -m pytest test_p2p.py -q *> "$dir\_p2p.txt"; $p2p = $LASTEXITCODE
  Pop-Location
  return @{ f2p_pass = ($f2p -eq 0); p2p_pass = ($p2p -eq 0); resolved = (($f2p -eq 0) -and ($p2p -eq 0)) }
}

function Invoke-Copilot($dir, $prompt) {
  $flat = ($prompt -replace "`r?`n", " ") -replace '"', '' -replace '\s+', ' '
  $out = Join-Path $dir "_cop.txt"
  Push-Location $dir
  try { & $cop -p $flat --allow-all-tools --allow-all-paths --add-dir $dir *> $out } catch { "__ERR__:$_" | Out-File $out }
  Pop-Location
}

if ((Test-Path $results) -and (-not $Append)) { Remove-Item $results -Force }
$TASKS = Get-ChildItem $taskdir -Directory | Where-Object { $_.Name -like $Filter }

foreach ($task in $TASKS) {
  $problem = Get-Content "$taskdir\$($task.Name)\problem.md" -Raw
  for ($rep = 1; $rep -le $Reps; $rep++) {

    # ---- Arm A: vanilla (no Phoenix; the agent self-judges) ----
    $dA = New-Instance $task
    $pA = "Read problem.md in the current directory and fix the bug in solution.py so it meets the described behavior. Do not change the function/class signatures. When confident the fix is correct, end with DONE."
    Invoke-Copilot $dA $pA
    $sA = Score $dA $task
    @{ id="$($task.Name)-A-$rep"; task=$task.Name; arm="A_vanilla"; rep=$rep; f2p=[int]$sA.f2p_pass; p2p=[int]$sA.p2p_pass; resolved=[int]$sA.resolved } | ConvertTo-Json -Compress | Add-Content $results
    Write-Output ("[{0,-14} A r{1}] resolved={2} (f2p={3} p2p={4})" -f $task.Name,$rep,$sA.resolved,$sA.f2p_pass,$sA.p2p_pass)
    Remove-Item $dA -Recurse -Force -ErrorAction SilentlyContinue

    # ---- Arm B: Phoenix (verify-heal loop enforced via the bundled tests-as-gate) ----
    $dB = New-Instance $task
    # Phoenix arm ALSO gets the hidden tests as the objective gate (this is the harness's job: an
    # objective check). It must phoenix_sense pytest green before claiming done.
    Copy-Item "$($task.FullName)\test_f2p.py" "$dB\test_f2p.py" -Force
    Copy-Item "$($task.FullName)\test_p2p.py" "$dB\test_p2p.py" -Force
    $pB = "Read problem.md and fix the bug in solution.py (do not change signatures, do NOT edit the test files). Use the phoenix MCP tools as your objective gate: after editing, call phoenix_sense with a command_exit check running python -m pytest -q expecting exit 0. If ok is false, read the failure, fix solution.py, and sense again until ok is true. Then phoenix_verify_trace. End with DONE only when the tests are green."
    Invoke-Copilot $dB $pB
    $sB = Score $dB $task
    @{ id="$($task.Name)-B-$rep"; task=$task.Name; arm="B_phoenix"; rep=$rep; f2p=[int]$sB.f2p_pass; p2p=[int]$sB.p2p_pass; resolved=[int]$sB.resolved } | ConvertTo-Json -Compress | Add-Content $results
    Write-Output ("[{0,-14} B r{1}] resolved={2} (f2p={3} p2p={4})" -f $task.Name,$rep,$sB.resolved,$sB.f2p_pass,$sB.p2p_pass)
    Remove-Item $dB -Recurse -Force -ErrorAction SilentlyContinue
  }
}
Write-Output "DONE -> $results"
