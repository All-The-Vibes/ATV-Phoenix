# scripts/run-north-star.ps1
# Azure north-star: SWE-bench Verified on ephemeral VM using Azure OpenAI (Entra auth, no keys).
# Arm A: gpt-5.1 vanilla. Arm B: gpt-5.1 + Phoenix verify-heal loop.
# Usage: pwsh -File scripts/run-north-star.ps1 [-Instances 20] [-DryRun]
param(
  [int]$Instances  = 20,
  [int]$MaxWorkers = 4,
  [string]$Location    = "eastus2",
  [string]$VmSize      = "Standard_D8s_v5",
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

# ── 1. Create ephemeral RG + VM with system-assigned managed identity ──
Log "Creating resource group $RgName..."
az group create --name $RgName --location $Location --output none

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
SSH "pip3 install swebench openai 2>&1 | tail -3"
SSH "curl -fsSL https://sh.rustup.rs | sh -s -- -y 2>&1 | tail -3"
SSH "git clone --depth 1 https://github.com/All-The-Vibes/ATV-Phoenix.git ~/ATV-Phoenix"
SSH "~/.cargo/bin/cargo build --release --manifest-path ~/ATV-Phoenix/Cargo.toml 2>&1 | tail -5"
Log "phoenix-mcp built on VM"

# ── 3. Upload the phoenix agent scripts ──
# arm_a.py: vanilla gpt-5.1 agent (Azure OpenAI, Entra token from IMDS)
# arm_b.py: same agent + phoenix verify-heal loop
$armA = @"
import json, os, sys, subprocess, textwrap
from openai import AzureOpenAI
from azure.identity import ManagedIdentityCredential
from azure.core.credentials import AccessToken

ENDPOINT   = os.environ["AOAI_ENDPOINT"]
DEPLOYMENT = os.environ["AOAI_DEPLOYMENT"]

class EntraTokenProvider:
    def __init__(self): self._cred = ManagedIdentityCredential()
    def __call__(self): return self._cred.get_token("https://cognitiveservices.azure.com/.default").token

client = AzureOpenAI(azure_endpoint=ENDPOINT, azure_ad_token_provider=EntraTokenProvider(), api_version="2024-12-01-preview")

def solve(instance_id, repo, issue):
    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role":"system","content":"You are a software engineer. Produce a minimal git diff patch that fixes the issue. Output ONLY the patch in unified diff format."},
            {"role":"user","content":f"Repository: {repo}\n\nIssue:\n{issue}\n\nProduce the patch:"}
        ],
        max_completion_tokens=4096
    )
    return resp.choices[0].message.content

instances = json.load(sys.stdin)
predictions = {}
for inst in instances:
    patch = solve(inst["instance_id"], inst["repo"], inst["problem_statement"])
    predictions[inst["instance_id"]] = {"instance_id":inst["instance_id"],"model_patch":patch,"model_name_or_path":"gpt-5.1-vanilla"}
    print(f"  solved {inst[chr(105)+chr(110)+chr(115)+chr(116)+chr(97)+chr(110)+chr(99)+chr(101)+chr(95)+chr(105)+chr(100)]}", flush=True)
json.dump(list(predictions.values()), sys.stdout)
"@
$armA | Set-Content -Encoding UTF8 "$env:TEMP\arm_a.py"
scp -o StrictHostKeyChecking=no "$env:TEMP\arm_a.py" "azureuser@${vmIp}:~/arm_a.py"

# arm_b adds phoenix verify-heal: sense the patch, heal until green, then submit
$armB = @"
import json, os, sys, subprocess, textwrap, tempfile, pathlib
from openai import AzureOpenAI
from azure.identity import ManagedIdentityCredential

ENDPOINT   = os.environ["AOAI_ENDPOINT"]
DEPLOYMENT = os.environ["AOAI_DEPLOYMENT"]
PHOENIX    = os.path.expanduser("~/ATV-Phoenix/target/release/phoenix-mcp")
MAX_HEALS  = 3

class EntraTokenProvider:
    def __init__(self): self._cred = ManagedIdentityCredential()
    def __call__(self): return self._cred.get_token("https://cognitiveservices.azure.com/.default").token

client = AzureOpenAI(azure_endpoint=ENDPOINT, azure_ad_token_provider=EntraTokenProvider(), api_version="2024-12-01-preview")

def llm(messages): return client.chat.completions.create(model=DEPLOYMENT, messages=messages, max_completion_tokens=4096).choices[0].message.content

def phoenix_sense(check_json):
    r = subprocess.run([PHOENIX,"sense",f"@{check_json}"], capture_output=True, text=True)
    import json as _j; return _j.loads(r.stdout)

def solve(instance_id, repo, issue):
    patch = llm([
        {"role":"system","content":"You are a software engineer. Produce a minimal git diff patch. Output ONLY the patch."},
        {"role":"user","content":f"Repository: {repo}\n\nIssue:\n{issue}\n\nProduce the patch:"}
    ])
    # Phoenix verify-heal: write check, sense, heal up to MAX_HEALS times
    with tempfile.NamedTemporaryFile(mode="w",suffix=".json",delete=False) as f:
        json.dump({"kind":"regex_in_file","target":"patch.diff","pattern":"^(---|\+\+\+|@@)","expect_match":True},f)
        check = f.name
    with open("patch.diff","w") as f: f.write(patch)
    for heal in range(MAX_HEALS):
        result = phoenix_sense(check)
        if result.get("ok"): break
        feedback = result.get("evidence","check failed")
        patch = llm([
            {"role":"system","content":"You are a software engineer fixing a patch. Output ONLY the corrected patch."},
            {"role":"user","content":f"Repository: {repo}\n\nIssue:\n{issue}\n\nYour previous patch failed verification:\n{feedback}\n\nProduce a corrected patch:"}
        ])
        with open("patch.diff","w") as f: f.write(patch)
    return patch

instances = json.load(sys.stdin)
predictions = {}
for inst in instances:
    patch = solve(inst["instance_id"], inst["repo"], inst["problem_statement"])
    predictions[inst["instance_id"]] = {"instance_id":inst["instance_id"],"model_patch":patch,"model_name_or_path":"gpt-5.1-phoenix"}
    print(f"  solved {inst[chr(105)+chr(110)+chr(115)+chr(116)+chr(97)+chr(110)+chr(99)+chr(101)+chr(95)+chr(105)+chr(100)]}", flush=True)
json.dump(list(predictions.values()), sys.stdout)
"@
$armB | Set-Content -Encoding UTF8 "$env:TEMP\arm_b.py"
scp -o StrictHostKeyChecking=no "$env:TEMP\arm_b.py" "azureuser@${vmIp}:~/arm_b.py"

# ── 4. Run inference (both arms) ──
Log "Running inference (Arm A vanilla, Arm B phoenix)..."
$envVars = "AOAI_ENDPOINT=$AoaiEndpoint AOAI_DEPLOYMENT=$AoaiDeployment"
SSH "$envVars pip3 install azure-identity 2>&1 | tail -2"
scp -o StrictHostKeyChecking=no "$(Join-Path $PSScriptRoot 'ns_fetch_instances.py')" "azureuser@${vmIp}:~/ns_fetch_instances.py"
SSH "pip3 install datasets 2>&1 | tail -2"
SSH "python3 ~/ns_fetch_instances.py $Instances > ~/instances.json"
SSH "$envVars python3 ~/arm_a.py < ~/instances.json > ~/pred_a.json"
SSH "$envVars python3 ~/arm_b.py < ~/instances.json > ~/pred_b.json"
Log "Inference complete"

# ── 5. Evaluate both arms ──
Log "Running evaluation (Docker)..."
SSH "cd ~/swe-bench && python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path ~/pred_a.json --max_workers $MaxWorkers --run_id arm_a_$today --output_dir ~/results_a 2>&1 | tail -10"
SSH "cd ~/swe-bench && python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path ~/pred_b.json --max_workers $MaxWorkers --run_id arm_b_$today --output_dir ~/results_b 2>&1 | tail -10"

# ── 6. Pull results ──
Log "Pulling results..."
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/results_a/*.json" "$outDir\"
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/results_b/*.json" "$outDir\"
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/pred_a.json" "$outDir\"
scp -o StrictHostKeyChecking=no "azureuser@${vmIp}:~/pred_b.json" "$outDir\"

# ── 7. Score ──
function Get-Score($dir, $arm) {
  $files = Get-ChildItem "$dir\*$arm*.json" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch "pred_" }
  if (-not $files) { return 0.0 }
  $t=0; $r=0
  foreach ($f in $files) { $d=$f | Get-Content -Raw | ConvertFrom-Json; foreach($k in $d.PSObject.Properties.Name){ $t++; if($d.$k.resolved){$r++} } }
  if($t -eq 0){return 0.0}
  return [math]::Round($r/$t, 4)
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

# ── 9. Delete VM ──
Log "Deleting resource group $RgName (async)..."
az group delete --name $RgName --yes --no-wait

# ── 10. Commit ──
git -C $repoRoot add "eval\"
git -C $repoRoot commit -m "chore(eval): north-star $today Arm B=$scoreB Arm A=$scoreA ($Instances instances)"
git -C $repoRoot push origin main
Log "Done. Results in eval/north-star/$today/"