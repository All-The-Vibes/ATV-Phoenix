# scripts/run-north-star.ps1
# Azure north-star: SWE-bench Verified on ephemeral VM using Azure OpenAI (Entra auth, no keys).
# Arm A: gpt-5.1 vanilla. Arm B: gpt-5.1 + Phoenix verify-heal loop.
# Usage: pwsh -File scripts/run-north-star.ps1 [-Instances 20] [-DryRun]
param(
  [int]$Instances  = 100,
  [int]$MaxWorkers = 4,
  [string]$Location    = "eastus2",
  [string]$VmSize      = "Standard_D16s_v5",
  [string]$RgName      = "rg-phoenix-northstar",
  [string]$VmName      = "phoenix-swe-eval",
  [string]$AoaiEndpoint = "https://nebula-aoai-txfcqm.openai.azure.com/",
  [string]$AoaiDeployment = "gpt-5.1",
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$repoRoot  = Split-Path $PSScriptRoot -Parent
$today     = (Get-Date).ToString("yyyy-MM-dd")
$outDir    = Join-Path $repoRoot "eval\north-star\$today"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
function Log($m) { Write-Output "[north-star] $m" }

if ($DryRun) { Log "DRY RUN -- no Azure resources created"; exit 0 }

# Terminal guard: everything from RG-create onward runs inside try/finally so the
# ephemeral RG is ALWAYS torn down -- even if bootstrap/inference/eval throws.
$rgCreated = $false
try {

# Pre-flight: nuke any stale RG left by a previously-failed run (prevents VM stacking).
if ((az group exists --name $RgName) -eq "true") {
  Log "Stale $RgName exists from a prior run -- deleting before recreate..."
  az group delete --name $RgName --yes --output none
}

# ── 1. Create ephemeral RG + VM with system-assigned managed identity ──
Log "Creating resource group $RgName..."
az group create --name $RgName --location $Location --output none
$rgCreated = $true

Log "Creating VM $VmName ($VmSize) with managed identity..."
$vmJson = az vm create `
  --resource-group $RgName --name $VmName `
  --image Ubuntu2204 --size $VmSize `
  --assign-identity "[system]" `
  --os-disk-delete-option Delete --nic-delete-option Delete `
  --admin-username azureuser --generate-ssh-keys `
  --output json | ConvertFrom-Json
$vmIp  = $vmJson.publicIpAddress
$vmId  = $vmJson.id
Log "VM ready: $vmIp  id=$vmId"

# Dead-man's switch: if THIS orchestrator process dies before the finally-block
# teardown (e.g. host reboot), Azure still auto-deallocates the VM so runaway
# compute billing is capped. The finally block is the primary teardown; this is backup.
az vm auto-shutdown --ids $vmId --time 0900 --output none 2>$null
Log "Auto-shutdown safety net armed (~0900 UTC deallocate)"

# Grant VM identity access to the Azure OpenAI resource (Cognitive Services User)
$vmPrincipal = az vm identity show --ids $vmId --query "principalId" -o tsv
$aoaiId = az cognitiveservices account show --name nebula-aoai-txfcqm --resource-group rg-fdpo --query "id" -o tsv
az role assignment create --assignee $vmPrincipal --role "Cognitive Services OpenAI User" --scope $aoaiId --output none
Log "Granted OpenAI User to VM identity"

function SSH($cmd) {
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=60 "azureuser@$vmIp" $cmd
}

# ── 2. Bootstrap VM ──
Log "Bootstrapping VM..."
SSH "sudo apt-get update -qq && sudo apt-get install -y docker.io python3-pip git curl 2>&1 | tail -5"
SSH "sudo systemctl start docker && sudo usermod -aG docker azureuser"
SSH "pip3 install swebench openai azure-identity datasets 2>&1 | tail -3"
SSH "curl -fsSL https://sh.rustup.rs | sh -s -- -y 2>&1 | tail -3"
SSH "git clone --depth 1 https://github.com/All-The-Vibes/ATV-Phoenix.git ~/ATV-Phoenix"
SSH "~/.cargo/bin/cargo build --release --manifest-path ~/ATV-Phoenix/Cargo.toml 2>&1 | tail -5"
Log "phoenix-mcp built on VM"

# ── 3. Upload the repo-aware agent ──
# real_agent.py clones each repo at base_commit, gives the model real file context,
# and (phoenix arm) verify-heals against `git apply --check` so patches apply by
# construction. Arm A = --arm vanilla (single-shot control); Arm B = --arm phoenix.
scp -o StrictHostKeyChecking=no "$(Join-Path $PSScriptRoot 'real_agent.py')" "azureuser@${vmIp}:~/real_agent.py"

# ── 4. Run inference (both arms) ──
Log "Running inference (Arm A vanilla, Arm B phoenix)..."
$envVars = "AOAI_ENDPOINT=$AoaiEndpoint AOAI_DEPLOYMENT=$AoaiDeployment"
SSH "$envVars pip3 install azure-identity 2>&1 | tail -2"
scp -o StrictHostKeyChecking=no "$(Join-Path $PSScriptRoot 'ns_fetch_instances.py')" "azureuser@${vmIp}:~/ns_fetch_instances.py"
SSH "pip3 install datasets 2>&1 | tail -2"
SSH "python3 ~/ns_fetch_instances.py $Instances > ~/instances.json"
SSH "$envVars python3 ~/real_agent.py --arm vanilla < ~/instances.json > ~/pred_a.json"
SSH "$envVars python3 ~/real_agent.py --arm phoenix  < ~/instances.json > ~/pred_b.json"
Log "Inference complete"

# ── 5. Evaluate both arms ──
Log "Running evaluation (Docker)..."
SSH "python3 -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path ~/pred_a.json --max_workers $MaxWorkers --run_id arm_a_$today --output_dir ~/results_a 2>&1 | tail -10"
SSH "python3 -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path ~/pred_b.json --max_workers $MaxWorkers --run_id arm_b_$today --output_dir ~/results_b 2>&1 | tail -10"

# ── 6. Pull results ──
Log "Pulling results..."
# The SWE-bench harness writes its report to HOME as <model_name_or_path>.<run_id>.json.
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/*arm_a_*.json" "$outDir\"
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/*arm_b_*.json" "$outDir\"
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/pred_a.json" "$outDir\"
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/pred_b.json" "$outDir\"

# ── 7. Score ──
function Get-Score($dir, $arm) {
  $files = Get-ChildItem "$dir\*$arm*.json" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch "pred_" }
  if (-not $files) { return 0.0 }
  # SWE-bench report schema: counts, not per-instance keys. resolved / submitted.
  $d = $files | Select-Object -First 1 | Get-Content -Raw | ConvertFrom-Json
  $den = if ($d.submitted_instances) { $d.submitted_instances } else { $Instances }
  if (-not $den -or $den -eq 0) { return 0.0 }
  return [math]::Round($d.resolved_instances / $den, 4)
}
$scoreA = Get-Score $outDir "arm_a"
$scoreB = Get-Score $outDir "arm_b"
Log "Arm A=$scoreA  Arm B=$scoreB"

# ── 8. Update scoreboard ──
$sb = Join-Path $repoRoot "eval\scoreboard.json"
$raw = [System.IO.File]::ReadAllBytes($sb)
if ($raw[0] -eq 0xEF){$raw=$raw[3..($raw.Length-1)]}
$board = [System.Text.Encoding]::UTF8.GetString($raw) | ConvertFrom-Json
if (-not $board.baseline.north_star) {
  $board.baseline | Add-Member -Force NoteProperty north_star @{date=$today;arm_b_resolved=$scoreB;arm_a_resolved=$scoreA;instances=$Instances;model=$AoaiDeployment}
  Log "North-star baseline established"
} else {
  $baseNS = $board.baseline.north_star.arm_b_resolved
  $delta = [math]::Round($scoreB - $baseNS, 4)
  Log "Delta vs baseline: $delta"
  if ($delta -lt -0.02) { Write-Warning "REGRESSION >2pp: Arm B=$scoreB baseline=$baseNS" }
}
$ns = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($sb, ($board | ConvertTo-Json -Depth 10), $ns)

# ── 9. Commit results (VM teardown happens in the finally block below) ──
git -C $repoRoot add "eval\"
git -C $repoRoot commit -m "chore(eval): north-star $today Arm B=$scoreB Arm A=$scoreA ($Instances instances)"
git -C $repoRoot push origin main
Log "Done. Results in eval/north-star/$today/"

}
finally {
  # Terminal guard: tear the ephemeral RG down no matter how we got here.
  if ($rgCreated) {
    Log "Teardown: deleting resource group $RgName (async)..."
    az group delete --name $RgName --yes --no-wait 2>$null
  } else {
    Log "Teardown: no RG was created, nothing to delete."
  }
}