# scripts/run-north-star.ps1
# Ephemeral Azure VM north-star: runs SWE-bench Verified (two-arm) on an Azure VM,
# pulls results, updates scoreboard, tears the VM down. No local Docker needed.
# Usage: pwsh -File scripts/run-north-star.ps1 [-Tasks 500] [-MaxWorkers 8] [-DryRun]
param(
  [int]$Tasks = 500,
  [int]$MaxWorkers = 8,
  [string]$Location = "eastus2",
  [string]$VmSize = "Standard_D16s_v5",
  [string]$RgName = "rg-phoenix-northstar",
  [string]$VmName = "phoenix-swe-eval",
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$today = (Get-Date).ToString("yyyy-MM-dd")
$outDir = Join-Path $repoRoot "eval\north-star\$today"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Log($msg) { Write-Output "[north-star] $msg" }

if ($DryRun) { Log "DRY RUN -- no Azure resources created"; exit 0 }

# -- 1. Create ephemeral resource group + VM --
Log "Creating resource group $RgName in $Location..."
az group create --name $RgName --location $Location --output none

Log "Creating VM $VmName ($VmSize)..."
$pubKey = (az sshkey list --query "[0].publicKey" -o tsv 2>$null)
$createArgs = @(
  "vm", "create",
  "--resource-group", $RgName,
  "--name", $VmName,
  "--image", "Ubuntu2204",
  "--size", $VmSize,
  "--os-disk-delete-option", "Delete",
  "--nic-delete-option", "Delete",
  "--admin-username", "azureuser",
  "--generate-ssh-keys",
  "--output", "json"
)
$vmJson = az @createArgs | ConvertFrom-Json
$vmIp = $vmJson.publicIpAddress
Log "VM ready at $vmIp"

# -- 2. Bootstrap VM --
function SSH($cmd) {
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 "azureuser@$vmIp" $cmd
}
Log "Installing dependencies..."
SSH "sudo apt-get update -qq && sudo apt-get install -y docker.io python3-pip git"
SSH "sudo systemctl start docker && sudo usermod -aG docker azureuser"
SSH "pip3 install swebench --quiet"

# -- 3. Clone repos --
Log "Cloning SWE-bench and ATV-Phoenix..."
SSH "git clone --depth 1 https://github.com/SWE-bench/SWE-bench.git ~/swe-bench"
SSH "git clone --depth 1 https://github.com/All-The-Vibes/ATV-Phoenix.git ~/ATV-Phoenix"

# -- 4. Run two-arm evaluation --
# Arm A: vanilla Copilot (no Phoenix gate)
# Arm B: Phoenix verify-heal (phoenix_accept enforced)
# Both use the same SWE-bench instance + scoring; arm is the prompt variant.
Log "Running Arm A (vanilla)..."
SSH "cd ~/swe-bench && python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path ~/ATV-Phoenix/eval/north-star/arm-a-predictions.json --max_workers $MaxWorkers --run_id arm-a-$today --output_dir ~/results-a 2>&1 | tail -20"

Log "Running Arm B (phoenix-gated)..."
SSH "cd ~/swe-bench && python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path ~/ATV-Phoenix/eval/north-star/arm-b-predictions.json --max_workers $MaxWorkers --run_id arm-b-$today --output_dir ~/results-b 2>&1 | tail -20"

# -- 5. Pull results --
Log "Pulling results..."
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/results-a/*.json" $outDir
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/results-b/*.json" $outDir

# -- 6. Score and update scoreboard --
Log "Scoring..."
$scoreFile = Join-Path $outDir "scores.json"
$scoreA = _ComputeScore (Join-Path $outDir "arm-a*.json")
$scoreB = _ComputeScore (Join-Path $outDir "arm-b*.json")
@{ date=$today; arm_a=$scoreA; arm_b=$scoreB } | ConvertTo-Json | Set-Content -Encoding UTF8 $scoreFile

$sb = Join-Path $repoRoot "eval\scoreboard.json"
$rawBytes = [System.IO.File]::ReadAllBytes($sb)
if ($rawBytes[0] -eq 0xEF) { $rawBytes = $rawBytes[3..($rawBytes.Length-1)] }
$board = [System.Text.Encoding]::UTF8.GetString($rawBytes) | ConvertFrom-Json
$baseNS = if ($board.baseline.north_star) { $board.baseline.north_star.arm_b_resolved } else { $scoreB }
if (-not $board.baseline.north_star) {
  $board.baseline | Add-Member -Force NoteProperty north_star @{ date=$today; arm_b_resolved=$scoreB; arm_a_resolved=$scoreA }
  Log "North-star baseline established: Arm B=$scoreB"
} else {
  $delta = [math]::Round($scoreB - $baseNS, 4)
  Log "North-star delta vs baseline: $delta (B=$scoreB baseline=$baseNS)"
  if ($delta -lt -0.02) { Write-Warning "REGRESSION >2pp: $delta -- notify Maverick" }
}
$board | ConvertTo-Json -Depth 10 | Out-File -Encoding UTF8 $sb

# -- 7. Delete VM + RG --
Log "Deleting resource group $RgName..."
az group delete --name $RgName --yes --no-wait
Log "VM deletion initiated (async). Results saved to $outDir"

# -- 8. Commit results --
git -C $repoRoot add "eval/north-star/$today/"
git -C $repoRoot add "eval/scoreboard.json"
git -C $repoRoot commit -m "chore(eval): north-star run $today Arm B=$scoreB Arm A=$scoreA"
Log "Done. Arm A=$scoreA Arm B=$scoreB"

function _ComputeScore([string]$pattern) {
  $files = Get-ChildItem $pattern -ErrorAction SilentlyContinue
  if (-not $files) { return 0.0 }
  $total = 0; $resolved = 0
  foreach ($f in $files) {
    $d = Get-Content -Raw $f | ConvertFrom-Json
    if ($d.PSObject.Properties["resolved"]) { $total++; if ($d.resolved) { $resolved++ } }
  }
  if ($total -eq 0) { return 0.0 }
  return [math]::Round($resolved / $total, 4)
}