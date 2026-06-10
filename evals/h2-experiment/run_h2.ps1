# H2-via-Phoenix runner: does an objective verifier (phoenix_sense+heal) change real Copilot outcomes
# vs vanilla self-judgment? Loops task x arm x rep, drives live copilot -p, scores with the hidden
# checker externally. Writes results.jsonl incrementally (survives interruption).
param([int]$Reps = 2)

$ErrorActionPreference = "Continue"
$root   = "C:\Users\shyamsridhar\code\ATV-Phoenix\evals\h2-experiment"
$taskdir = "$root\tasks"
$cop    = "$env:APPDATA\npm\copilot.cmd"
$results = "$root\results.jsonl"

$TASKS = @(
  @{ name="slugify";  fn="slugify";          spec="slugify_spec.txt";  check="slugify_check.py";  done="def slugify" },
  @{ name="duration"; fn="format_duration";  spec="duration_spec.txt"; check="duration_check.py"; done="def format_duration" },
  @{ name="roman";    fn="to_roman";         spec="roman_spec.txt";    check="roman_check.py";    done="def to_roman" }
)

function New-Trial($task, $arm) {
  $dir = Join-Path $env:TEMP ("h2_" + $task.name + "_" + $arm + "_" + [guid]::NewGuid().ToString("N").Substring(0,6))
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  Copy-Item "$taskdir\solution_stub.py" "$dir\solution.py" -Force
  return $dir
}

function Invoke-Copilot($dir, $prompt, $timeoutSec) {
  # Direct call operator handles quoting correctly (Start-Process/Start-Job both mangle it).
  # Flatten newlines to spaces (newlines in the arg also break the cmd shim).
  $flat = ($prompt -replace "`r?`n", " ") -replace '"', '' -replace '\s+', ' '
  $outFile = Join-Path $dir "_cop_out.txt"
  Push-Location $dir
  try {
    & $cop -p $flat --allow-all-tools --allow-all-paths --add-dir $dir *> $outFile
  } catch {
    "__ERR__:$_" | Out-File $outFile
  }
  Pop-Location
  return (Get-Content $outFile -Raw -ErrorAction SilentlyContinue)
}

if (Test-Path $results) { Remove-Item $results -Force }

foreach ($task in $TASKS) {
  $spec = Get-Content "$taskdir\$($task.spec)" -Raw
  for ($rep = 1; $rep -le $Reps; $rep++) {

    # ---- Arm A: vanilla self-judgment (no checker visible, no phoenix mention) ----
    $dirA = New-Trial $task "A"
    $promptA = "Implement the function ``$($task.fn)`` in the file solution.py in the current directory, exactly per this specification:`n`n$spec`n`nWhen you are confident the implementation is correct, end your reply with the single word DONE."
    $outA = Invoke-Copilot $dirA $promptA 200
    # score externally
    Copy-Item "$taskdir\$($task.check)" "$dirA\check.py" -Force
    Push-Location $dirA; python check.py *> "$dirA\score.txt"; $passA = ($LASTEXITCODE -eq 0); Pop-Location
    $claimedA = ($outA -match "DONE")
    $phoenixA = Test-Path "$dirA\.phoenix\trace.jsonl"
    $rowA = @{ id="$($task.name)-A-$rep"; task=$task.name; arm="A_vanilla"; rep=$rep; claimed_done=[int][bool]$claimedA; actual_pass=[int][bool]$passA; used_phoenix=[int][bool]$phoenixA } | ConvertTo-Json -Compress
    Add-Content $results $rowA
    Write-Output ("[{0,-9} A rep{1}] claimed={2} actual_pass={3} phoenix={4}" -f $task.name,$rep,$claimedA,$passA,$phoenixA)
    Remove-Item $dirA -Recurse -Force -ErrorAction SilentlyContinue

    # ---- Arm B: phoenix-enforced verify+heal (checker present) ----
    $dirB = New-Trial $task "B"
    Copy-Item "$taskdir\$($task.check)" "$dirB\check.py" -Force
    $promptB = "Implement the function ``$($task.fn)`` in solution.py in the current directory, per this spec:`n`n$spec`n`nThere is an acceptance checker ``check.py`` (do NOT read or edit it). Use the phoenix MCP tools to guarantee correctness: after writing solution.py, call phoenix_sense with a command_exit check whose target runs python on check.py (argv: python, check.py) and expects exit code 0. If the result ok is false, fix solution.py and call phoenix_sense again; repeat until ok is true. End with the single word DONE."
    $outB = Invoke-Copilot $dirB $promptB 260
    Push-Location $dirB; python check.py *> "$dirB\score.txt"; $passB = ($LASTEXITCODE -eq 0); Pop-Location
    $claimedB = ($outB -match "DONE")
    $phoenixB = Test-Path "$dirB\.phoenix\trace.jsonl"
    $rowB = @{ id="$($task.name)-B-$rep"; task=$task.name; arm="B_phoenix"; rep=$rep; claimed_done=[int][bool]$claimedB; actual_pass=[int][bool]$passB; used_phoenix=[int][bool]$phoenixB } | ConvertTo-Json -Compress
    Add-Content $results $rowB
    Write-Output ("[{0,-9} B rep{1}] claimed={2} actual_pass={3} phoenix={4}" -f $task.name,$rep,$claimedB,$passB,$phoenixB)
    Remove-Item $dirB -Recurse -Force -ErrorAction SilentlyContinue
  }
}
Write-Output "DONE. results -> $results"

