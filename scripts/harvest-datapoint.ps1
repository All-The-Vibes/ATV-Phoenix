# scripts/harvest-datapoint.ps1
# Harvest a Phoenix dream beat as a labeled eval datapoint.
# Quality gates (all must pass): saw_red=true, green_after_red=true, trace_intact=true,
# blast-radius <=3 changed files, LAW 2 PII lint on problem content.
# On pass: writes evals/dogfood/tasks/<IssueNumber>-<IssueSlug>/ with:
#   problem.md, solution.py (or solution.<ext>), test_f2p.py, test_p2p.py, meta.json
# Exit 0 = harvested; Exit 1 = gate failure (reason printed to stdout).
param(
    [Parameter(Mandatory)][string]$IssueNumber,
    [Parameter(Mandatory)][string]$IssueSlug,
    [Parameter(Mandatory)][string]$ProblemFile,
    [Parameter(Mandatory)][string]$SolutionFile,
    [Parameter(Mandatory)][string]$TestF2PFile,
    [Parameter(Mandatory)][string]$TestP2PFile,
    [Parameter(Mandatory)][string]$AcceptProofFile,
    [Parameter(Mandatory)][string]$ChangedFiles,
    [string]$CommitSha = "",
    [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"

# --- GATE 1: Accept proof quality ---
if (-not (Test-Path $AcceptProofFile)) {
    Write-Output "GATE_FAIL: AcceptProofFile not found: $AcceptProofFile"; exit 1
}
try {
    $proof = Get-Content -Raw $AcceptProofFile | ConvertFrom-Json
} catch {
    Write-Output "GATE_FAIL: AcceptProofFile not valid JSON: $_"; exit 1
}
if (-not $proof.saw_red) {
    Write-Output "GATE_FAIL: saw_red=false -- vacuous gate, not a real failure-first fix"; exit 1
}
if (-not $proof.green_after_red) {
    Write-Output "GATE_FAIL: green_after_red=false -- check did not complete red->green"; exit 1
}
if (-not $proof.trace_intact) {
    Write-Output "GATE_FAIL: trace_intact=false -- tampered or broken hash chain"; exit 1
}

# --- GATE 2: Blast-radius budget ---
$files = ($ChangedFiles -split '[,\r\n]') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
if ($files.Count -gt 3) {
    Write-Output "GATE_FAIL: blast_radius=$($files.Count) > 3 -- patch too broad for a reliable eval task"; exit 1
}

# --- GATE 3: LAW 2 PII lint on problem content ---
if (-not (Test-Path $ProblemFile)) {
    Write-Output "GATE_FAIL: ProblemFile not found: $ProblemFile"; exit 1
}
$problemContent = Get-Content -Raw $ProblemFile
if ($problemContent -match '[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}') {
    Write-Output "GATE_FAIL: LAW2_PII -- email address found in problem.md"; exit 1
}
if ($problemContent -match '(?m)(?<![`\w])@[a-zA-Z][a-zA-Z0-9_\-]{2,}(?![`\w])') {
    Write-Output "GATE_FAIL: LAW2_PII -- @handle found in problem.md"; exit 1
}

# --- All gates passed: write task directory ---
if (-not $OutDir) {
    $OutDir = Join-Path (Split-Path $PSScriptRoot -Parent) "evals\dogfood\tasks"
}
$slug = "$IssueNumber-$IssueSlug"
$taskDir = Join-Path $OutDir $slug
New-Item -ItemType Directory -Force -Path $taskDir | Out-Null

Copy-Item $ProblemFile (Join-Path $taskDir "problem.md") -Force
$ext = [System.IO.Path]::GetExtension($SolutionFile).TrimStart('.')
$solutionName = if ($ext -and $ext -ne "py") { "solution.$ext" } else { "solution.py" }
Copy-Item $SolutionFile (Join-Path $taskDir $solutionName) -Force
Copy-Item $TestF2PFile  (Join-Path $taskDir "test_f2p.py") -Force
Copy-Item $TestP2PFile  (Join-Path $taskDir "test_p2p.py") -Force

$traceDigest = if ($proof.check_digest) { $proof.check_digest } else { "unknown" }
$meta = [ordered]@{
    issue_number  = $IssueNumber
    issue_slug    = $IssueSlug
    commit_sha    = $CommitSha
    trace_digest  = $traceDigest
    saw_red       = $true
    changed_files = $files
    harvested_at  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText((Join-Path $taskDir "meta.json"), ($meta | ConvertTo-Json), $utf8NoBom)
Write-Output "HARVESTED: $taskDir"
exit 0

