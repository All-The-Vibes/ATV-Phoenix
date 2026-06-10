# H3 memory-lift runner: does injecting project-specific context lift task success?
# Arm A = spec only (model uses default convention -> should FAIL the hidden convention checker).
# Arm B = spec + injected context (the convention) -> should PASS.
# The ONLY difference is the context. Scored externally by the hidden checker.
param([int]$Reps = 2)

$ErrorActionPreference = "Continue"
$root    = "C:\Users\shyamsridhar\code\ATV-Phoenix\evals\h3-experiment"
$taskdir = "$root\tasks"
$cop     = "$env:APPDATA\npm\copilot.cmd"
$results = "$root\results.jsonl"

$TASKS = @(
  @{ name="status"; fn="status_label";  spec="status_spec.txt"; ctx="status_context.txt"; check="status_check.py" },
  @{ name="money";  fn="format_money";  spec="money_spec.txt";  ctx="money_context.txt";  check="money_check.py" },
  @{ name="userid"; fn="user_id";       spec="userid_spec.txt"; ctx="userid_context.txt"; check="userid_check.py" }
)

function New-Trial($task) {
  $dir = Join-Path $env:TEMP ("h3_" + $task.name + "_" + [guid]::NewGuid().ToString("N").Substring(0,6))
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  "def PLACEHOLDER(): raise NotImplementedError" | Set-Content "$dir\solution.py"
  return $dir
}

function Invoke-Copilot($dir, $prompt) {
  $flat = ($prompt -replace "`r?`n", " ") -replace '"', '' -replace '\s+', ' '
  $outFile = Join-Path $dir "_o.txt"
  Push-Location $dir
  try { & $cop -p $flat --allow-all-tools --allow-all-paths --add-dir $dir *> $outFile } catch { "__ERR__:$_" | Out-File $outFile }
  Pop-Location
  return (Get-Content $outFile -Raw -ErrorAction SilentlyContinue)
}

function Score($dir, $task) {
  Copy-Item "$taskdir\$($task.check)" "$dir\check.py" -Force
  Push-Location $dir; python check.py *> "$dir\_score.txt"; $pass = ($LASTEXITCODE -eq 0); Pop-Location
  return $pass
}

if (Test-Path $results) { Remove-Item $results -Force }

foreach ($task in $TASKS) {
  $spec = Get-Content "$taskdir\$($task.spec)" -Raw
  $ctx  = Get-Content "$taskdir\$($task.ctx)" -Raw
  for ($rep = 1; $rep -le $Reps; $rep++) {

    # Arm A: spec only
    $dirA = New-Trial $task
    $pA = "Implement the function $($task.fn) in solution.py in the current directory per this spec: $spec When confident, end with DONE."
    $null = Invoke-Copilot $dirA $pA
    $passA = Score $dirA $task
    @{ id="$($task.name)-A-$rep"; task=$task.name; arm="A_nocontext"; rep=$rep; actual_pass=[int][bool]$passA } | ConvertTo-Json -Compress | Add-Content $results
    Write-Output ("[{0,-7} A rep{1}] pass={2}" -f $task.name,$rep,$passA)
    Remove-Item $dirA -Recurse -Force -ErrorAction SilentlyContinue

    # Arm B: spec + injected context
    $dirB = New-Trial $task
    $pB = "Implement the function $($task.fn) in solution.py in the current directory per this spec: $spec  $ctx  Follow the project convention exactly. When confident, end with DONE."
    $null = Invoke-Copilot $dirB $pB
    $passB = Score $dirB $task
    @{ id="$($task.name)-B-$rep"; task=$task.name; arm="B_context"; rep=$rep; actual_pass=[int][bool]$passB } | ConvertTo-Json -Compress | Add-Content $results
    Write-Output ("[{0,-7} B rep{1}] pass={2}" -f $task.name,$rep,$passB)
    Remove-Item $dirB -Recurse -Force -ErrorAction SilentlyContinue
  }
}
Write-Output "DONE -> $results"
