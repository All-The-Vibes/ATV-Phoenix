#requires -Version 5
<#
.SYNOPSIS
  ATV-Phoenix Ralph loop driver — Geoffrey Huntley's `while :; do cat PROMPT.md | agent; done`
  (https://ghuntley.com/ralph), Phoenix-gated.

.DESCRIPTION
  The DRIVER decides completion, not the agent. Each loop runs the coding agent (GitHub Copilot CLI)
  with a fixed PROMPT in a FRESH context. The filesystem (.phoenix-ralph/) is the brain. The loop
  stops only when the top-level acceptance check is proven FAILURE-FIRST satisfied
  (red->green, currently green) on an intact tamper-evident trace -- via `phoenix-mcp accept`.

  Honest framing: each `copilot -p` is one-shot, so this external loop IS the persistence mechanism
  (Copilot has no Claude-Code-style re-injection hook). The agent proposes state changes; the driver
  proves them.

.NOTES
  State dir layout (.phoenix-ralph/):
    PROMPT.md        fixed per-loop instructions (re-read every iteration)
    backlog.json     [{id,title,check:<phoenix_sense Check>,done:bool}] -- each item gate is OBJECTIVE
    progress.md      append-only cross-iteration learnings (survives the fresh context)
    done-check.json  the single top-level acceptance Check that ends the loop when proven
    completed.json   written by the DRIVER on success (proof bundle) -- never by the agent

  Windows / PS5.1 note:
    This script self-promotes to PowerShell 7 (pwsh) if running under PS < 6.
    PS 5.1 mangles native-command arguments that contain embedded double-quotes, angle brackets,
    or shell metacharacters — the exact characters that appear in normal PROMPT.md content.
    The driver re-execs itself under pwsh so the user never has to think about which shell to use.
    (Issue #8 root-cause analysis: a 4946-char prompt arrived as 12 split argv tokens under PS5.1;
    under pwsh it arrived as 1 intact token.)
#>

[CmdletBinding()]
param(
  [string]$Dir = ".phoenix-ralph",
  [int]$MaxLoops = 50,
  [int]$MaxMinutes = 120,
  [int]$NoProgressStop = 3,
  [string]$PhoenixBin = "",
  [string]$Copilot = "",
  [switch]$AllowPreGreen,
  [switch]$ReScope,
  [switch]$NoTag
)

# ---- Windows PS5.1 guard: self-promote to pwsh ----
if ($PSVersionTable.PSVersion.Major -lt 6) {
  if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    Write-Host "[ralph] FATAL: phoenix-ralph requires PowerShell 7+ on Windows (PS 5.1 mangles agent prompt args)." -ForegroundColor Red
    Write-Host "[ralph]        Install PowerShell 7: https://aka.ms/powershell" -ForegroundColor Red
    exit 2
  }
  $forwardArgs = @()
  foreach ($entry in $PSBoundParameters.GetEnumerator()) {
    if ($entry.Value -is [System.Management.Automation.SwitchParameter]) {
      if ($entry.Value.IsPresent) { $forwardArgs += "-$($entry.Key)" }
    } else {
      $forwardArgs += "-$($entry.Key)", "$($entry.Value)"
    }
  }
  & pwsh -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath @forwardArgs
  exit $LASTEXITCODE
}
# Belt-and-suspenders on PS 7+: pin Standard arg passing so native commands receive verbatim argv.
$PSNativeCommandArgumentPassing = 'Standard'

$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "[ralph] $m" -ForegroundColor Cyan }
function Warn($m){ Write-Host "[ralph] $m" -ForegroundColor Yellow }
function Die($m){ Write-Host "[ralph] FATAL: $m" -ForegroundColor Red; exit 2 }
function FileSig($p){ if (Test-Path $p) { (Get-FileHash $p -Algorithm SHA256).Hash } else { "absent" } }

$repo = (Get-Location).Path
$state = Join-Path $repo $Dir
$doneCheck = Join-Path $state "done-check.json"
$acceptanceContract = Join-Path $state "acceptance-contract.json"
$acceptanceContractArg = [System.IO.Path]::GetRelativePath($repo, $acceptanceContract)
$prompt = Join-Path $state "PROMPT.md"

# ---- locate binaries ----
if (-not $PhoenixBin) {
  $cand = @("$repo\target\release\phoenix-mcp.exe","$repo\target\debug\phoenix-mcp.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($cand) { $PhoenixBin = $cand } elseif (Get-Command phoenix-mcp -ErrorAction SilentlyContinue) { $PhoenixBin = "phoenix-mcp" }
}
if (-not $PhoenixBin) { Die "phoenix-mcp not found. Build it (cargo build --release) or pass -PhoenixBin." }
if (-not $Copilot) {
  if (Test-Path "$env:APPDATA\npm\copilot.cmd") { $Copilot = "$env:APPDATA\npm\copilot.cmd" } elseif (Get-Command copilot -ErrorAction SilentlyContinue) { $Copilot = "copilot" }
}
if (-not $Copilot) { Die "copilot CLI not found. Install it or pass -Copilot." }

# ---- validate state ----
if (-not (Test-Path $doneCheck)) { Die "missing $doneCheck (the top-level acceptance check)." }
if (-not (Test-Path $prompt))    { Die "missing $prompt (the fixed per-loop instructions)." }
$env:PHOENIX_WORKSPACE = $repo
# Pass the check by @file (not inline JSON) — avoids PowerShell->exe quote-mangling.
$doneArg = "@$doneCheck"

function AssertContract($where) {
  & $PhoenixBin contract-validate $acceptanceContractArg $doneArg | Out-Null
  if ($LASTEXITCODE -ne 0) { Die "acceptance contract mismatch $where -- stopping; use -ReScope only with an intentional currently-RED replacement." }
}

# ---- baseline: the done-check should start RED so completion can be proven failure-first ----
Info "binaries: phoenix=$PhoenixBin  copilot=$Copilot"
Info "baseline sense of done-check..."
& $PhoenixBin sense $doneArg | Out-Null
$baselineGreen = ($LASTEXITCODE -eq 0)
if ($baselineGreen -and -not $AllowPreGreen) {
  Die "done-check is ALREADY GREEN at start -- it can't prove failure-first (it'd be a vacuous gate). Re-target the check at the real unmet goal, or pass -AllowPreGreen if it's legitimately satisfied."
}

# ---- freeze the acceptance scope (or explicitly replace it with a currently-RED check) ----
if ($ReScope) {
  Info "explicitly re-scoping acceptance contract..."
  & $PhoenixBin contract-rescope $acceptanceContractArg $doneArg | Out-Null
  if ($LASTEXITCODE -ne 0) { Die "acceptance contract re-scope rejected; the replacement must be currently RED." }
} else {
  Info "freezing initial acceptance contract..."
  & $PhoenixBin contract-freeze $acceptanceContractArg $doneArg | Out-Null
  if ($LASTEXITCODE -ne 0) { Die "acceptance contract freeze rejected; refusing to run with a changed or non-RED done-check." }
}

# ---- the loop ----
$start = Get-Date
$noProgress = 0
$lastSig = ""
$loop = 0
$traceFile = Join-Path $repo ".phoenix\trace.jsonl"
$backlog = Join-Path $state "backlog.json"

while ($loop -lt $MaxLoops) {
  $loop++
  if (((Get-Date) - $start).TotalMinutes -ge $MaxMinutes) { Warn "wall-clock budget ($MaxMinutes min) reached."; break }

  # 1. DRIVER decides done: is the done-check failure-first satisfied on an intact trace?
  AssertContract "before accept"
  & $PhoenixBin accept $doneArg 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) {
    Info "done-check ACCEPTED (failure-first, green). Goal proven complete."
    # Issue #13: warn when the done-check greens but backlog items are still done:false.
    # This is a symptom of a weak-proxy gate — the check encoded something shallower than the
    # full goal (positive assertions only, no negative/absence assertions). The warning is
    # non-fatal: the failure-first proof is valid; the human should tighten the gate.
    if (Test-Path $backlog) {
      try {
        $bl = Get-Content $backlog -Raw | ConvertFrom-Json
        $unfinished = @($bl | Where-Object { $_.PSObject.Properties["done"] -and $_.done -eq $false }).Count
        if ($unfinished -gt 0) {
          Warn ("done-check green but {0} backlog item(s) still done:false -- POSSIBLE UNDER-SPECIFIED GATE. " +
                "Your done-check may be a proxy, not the full goal. " +
                "Add negative/absence assertions (the legacy thing is gone, all surfaces migrated). " +
                "See https://github.com/All-The-Vibes/ATV-Phoenix/issues/13") -f $unfinished
        }
      } catch { <# non-fatal: malformed backlog.json -- skip warning #> }
    }
    break
  }

  # 2. Capture pre-turn trace/backlog signature to detect launch failures.
  $preTurnSig = (FileSig $traceFile) + "|" + (FileSig $backlog)

  # 3. Fresh-context agent turn (Huntley: one task per loop, brain on disk).
  #    Write the prompt to a temp file and pass it via stdin to avoid PS5.1/cmd metachar mangling.
  #    (The @file convention already used for phoenix-mcp checks applies here too — see issue #8.)
  Info "iteration $loop/$MaxLoops -- invoking agent (fresh context)..."
  $tmpPrompt = [System.IO.Path]::GetTempFileName()
  try {
    [System.IO.File]::WriteAllText($tmpPrompt, (Get-Content $prompt -Raw), [System.Text.Encoding]::UTF8)
    Get-Content $tmpPrompt -Raw | & $Copilot --stdin --allow-all-tools --allow-all-paths --add-dir $repo
    $agentExit = $LASTEXITCODE
  } finally {
    Remove-Item $tmpPrompt -ErrorAction SilentlyContinue
  }

  AssertContract "after agent iteration $loop"

  # 4. Detect launch failure: agent exited nonzero AND trace/backlog signature is unchanged.
  #    That pattern means the process never started (or started and immediately crashed) rather than
  #    ran and chose not to change anything. Fail fast with a clear message instead of burning iterations.
  $postTurnSig = (FileSig $traceFile) + "|" + (FileSig $backlog)
  if ($agentExit -ne 0 -and $postTurnSig -eq $preTurnSig) {
    Die "agent launch failure detected: copilot exited $agentExit and no trace/backlog change was observed. The agent process likely never started. Check your Copilot CLI installation and PROMPT.md for unsupported syntax."
  } elseif ($agentExit -ne 0) {
    Warn "copilot exited $agentExit (but trace/backlog changed — agent ran, may have partially succeeded)."
  }

  # 5. Trace must stay intact (tamper-evidence). A broken chain means we can't trust completion.
  & $PhoenixBin verify-trace 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) { Die "trace chain BROKEN after iteration $loop -- stopping (possible tampering/corruption)." }

  # 6. No-progress detection: hash trace + backlog. Unchanged N times in a row => stuck.
  $sig = $postTurnSig
  if ($sig -eq $lastSig) { $noProgress++; Warn "no state change ($noProgress/$NoProgressStop)." } else { $noProgress = 0 }
  $lastSig = $sig
  if ($noProgress -ge $NoProgressStop) { Warn "no progress for $NoProgressStop iterations -- stopping (stuck; this is a planning problem)."; break }
}

# ---- completion: DRIVER writes the proof bundle + tag (never the agent) ----
AssertContract "before accept"
$acc = & $PhoenixBin accept $doneArg 2>$null
if ($LASTEXITCODE -eq 0) {
  $proof = [ordered]@{
    completed_at   = (Get-Date).ToString("o")
    iterations     = $loop
    accept         = ($acc | ConvertFrom-Json)
    trace_sha256   = (FileSig $traceFile)
    backlog_sha256 = (FileSig $backlog)
  }
  $proofJson = $proof | ConvertTo-Json -Depth 6
  $proofJson | Set-Content (Join-Path $state "completed.json")
  # Phase-aware proof: also write completed.<check_digest_short>.json so multi-phase runs
  # accumulate an auditable chain of proofs instead of each phase overwriting the last.
  $digestShort = if ($proof.accept.check_digest) { $proof.accept.check_digest.Substring(0,12) } else { (Get-Date).ToString("yyyyMMdd-HHmmss") }
  $phaseProof = Join-Path $state "completed.$($digestShort).json"
  $proofJson | Set-Content $phaseProof
  Info "COMPLETE in $loop iterations. Proof -> $Dir\completed.json + completed.$($digestShort).json"
  if (-not $NoTag -and (Test-Path "$repo\.git")) {
    try {
      $tag = "phoenix-ralph-$((Get-Date).ToString('yyyyMMdd-HHmmss'))"
      & git -C $repo tag -a $tag -m "phoenix-ralph: done-check proven failure-first ($loop iterations)" 2>$null
      if ($LASTEXITCODE -eq 0) { Info "git tag: $tag" } else { Warn "tag skipped (git exit $LASTEXITCODE; needs at least one commit)." }
    } catch { Warn "tag skipped: $_" }
  }
  exit 0
} else {
  Warn "stopped WITHOUT proving the done-check ($loop iterations). Latest accept verdict:"
  Write-Host $acc
  exit 1
}