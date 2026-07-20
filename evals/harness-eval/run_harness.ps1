param(
    [string]$TasksDir = "",
    [string]$Filter = "*",
    $Seeds = "104729,130363,155921,181081,205759",
    [string]$OutputDir = "",
    [string]$CopilotCommand = "",
    [switch]$FreezePins,
    [string]$PinnedProtocolFile = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RunnerVersion = "1.0.0"
$Model = "gpt-5.6-sol"
$DefaultSeeds = @(104729, 130363, 155921, 181081, 205759)
$ExpectedTasks = @("cache-lru", "csv-parser", "date-range", "hard-dedupe",
    "hard-slugify", "hard-titlecase", "hard-truncate", "money-round", "retry-backoff")
$HarnessDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $HarnessDir "..\..")).Path
$DefaultTasksDir = Join-Path $RepoRoot "evals\swe-bench-lite\tasks"
$DefaultOutputDir = Join-Path $HarnessDir "results"
$Verifier = Join-Path $HarnessDir "verifiers.py"
$ProtocolPath = Join-Path $HarnessDir "protocol.json"
$RunnerPath = $MyInvocation.MyCommand.Path

function Get-Sha256Bytes([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-Sha256Text([string]$Text) {
    return Get-Sha256Bytes ([Text.Encoding]::UTF8.GetBytes($Text))
}

function Get-FileSha256([string]$Path) {
    return Get-Sha256Bytes ([IO.File]::ReadAllBytes($Path))
}

function Get-CanonicalJson($Value) {
    return (ConvertTo-Json -InputObject $Value -Depth 20 -Compress)
}

function Write-Utf8NoBom([string]$Path, [string]$Text, [bool]$Append) {
    $Encoding = New-Object Text.UTF8Encoding($false)
    if ($Append) {
        [IO.File]::AppendAllText($Path, $Text + [Environment]::NewLine, $Encoding)
    } else {
        [IO.File]::WriteAllText($Path, $Text, $Encoding)
    }
}

function Write-JsonAtomic([string]$Path, $Value) {
    $TemporaryPath = "$Path.$([guid]::NewGuid().ToString("N")).tmp"
    $BackupPath = "$Path.$([guid]::NewGuid().ToString("N")).bak"
    try {
        Write-Utf8NoBom $TemporaryPath (Get-CanonicalJson $Value) $false
        if (Test-Path -LiteralPath $Path) {
            [IO.File]::Replace($TemporaryPath, $Path, $BackupPath)
        } else {
            [IO.File]::Move($TemporaryPath, $Path)
        }
    } finally {
        Remove-Item -LiteralPath $TemporaryPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $BackupPath -Force -ErrorAction SilentlyContinue
    }
}

function Set-ObjectProperty($Value, [string]$Name, $PropertyValue) {
    if ($Value -is [Collections.IDictionary]) {
        $Value[$Name] = $PropertyValue
    } else {
        $Value | Add-Member -NotePropertyName $Name -NotePropertyValue $PropertyValue -Force
    }
}

function Fail([string]$Message) {
    [Console]::Error.WriteLine("ERROR: $Message")
    exit 1
}

function Test-ExactProperties($Value, [string[]]$Names) {
    if ($null -eq $Value) { return $false }
    $Actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $Expected = @($Names | Sort-Object)
    return (Get-CanonicalJson $Actual) -eq (Get-CanonicalJson $Expected)
}

function Test-VerificationLevel($Value, [string]$FailureReason) {
    if (-not (Test-ExactProperties $Value @("pass", "reason"))) { return $false }
    if ($Value.pass -isnot [bool] -or $Value.reason -isnot [string]) { return $false }
    if ($Value.pass) { return $Value.reason -ceq "passed" }
    return $Value.reason -ceq $FailureReason
}

try {
    $Seeds = @(($Seeds -split "[,\s;]+") | Where-Object { $_ } |
        ForEach-Object { [int]$_.Trim() })
} catch {
    Fail "seeds must be comma-separated integers"
}

$UsingTasksOverride = -not [string]::IsNullOrWhiteSpace($TasksDir)
$UsingOutputOverride = -not [string]::IsNullOrWhiteSpace($OutputDir)
$UsingCopilotOverride = -not [string]::IsNullOrWhiteSpace($CopilotCommand)
$UsingFilterOverride = $Filter -ne "*"
$UsingSeedsOverride = (Get-CanonicalJson @($Seeds)) -ne (Get-CanonicalJson $DefaultSeeds)
$MechanicsOnly = $UsingTasksOverride -or $UsingOutputOverride -or $UsingCopilotOverride -or
    $UsingFilterOverride -or $UsingSeedsOverride

if (-not $TasksDir) { $TasksDir = $DefaultTasksDir }
if (-not $OutputDir) { $OutputDir = $DefaultOutputDir }
if (-not $CopilotCommand) { $CopilotCommand = Join-Path $env:APPDATA "npm\copilot.cmd" }
if (-not $PinnedProtocolFile) {
    $PinnedProtocolFile = Join-Path $OutputDir "protocol-pinned.json"
}
if ($FreezePins -and $MechanicsOnly) {
    Fail "-FreezePins requires the default production tasks, seeds, output, and Copilot command"
}

if (-not (Test-Path -LiteralPath $TasksDir -PathType Container)) { Fail "task directory is missing" }
if (-not (Test-Path -LiteralPath $Verifier -PathType Leaf)) { Fail "verifier is missing" }
if (-not (Test-Path -LiteralPath $ProtocolPath -PathType Leaf)) { Fail "protocol is missing" }
if ($Seeds.Count -lt 1 -or $Seeds.Count -gt 20 -or @($Seeds | Select-Object -Unique).Count -ne $Seeds.Count) {
    Fail "seeds must be 1-20 unique integers"
}

$Tasks = @(Get-ChildItem -LiteralPath $TasksDir -Directory |
    Where-Object { $_.Name -like $Filter } | Sort-Object Name)
if ($Tasks.Count -lt 1 -or $Tasks.Count -gt 50) { Fail "task selection must contain 1-50 tasks" }
if (-not $MechanicsOnly -and (Get-CanonicalJson @($Tasks.Name)) -ne (Get-CanonicalJson $ExpectedTasks)) {
    Fail "production run requires the complete preregistered task set"
}
foreach ($Task in $Tasks) {
    foreach ($Name in @("problem.md", "solution.py", "test_f2p.py", "test_p2p.py")) {
        if (-not (Test-Path -LiteralPath (Join-Path $Task.FullName $Name) -PathType Leaf)) {
            Fail "task package is incomplete: $($Task.Name)"
        }
    }
}

$ProtocolText = Get-Content -LiteralPath $ProtocolPath -Raw
try { $Protocol = $ProtocolText | ConvertFrom-Json }
catch { Fail "protocol JSON is malformed" }
if (-not (Test-ExactProperties $Protocol @(
            "schema_version", "protocol_id", "protocol_status", "execution_status", "purpose",
            "pinning", "execution", "mocks", "checks", "metrics", "evidence"
        )) -or
    $Protocol.schema_version -cne "1.0" -or
    $Protocol.protocol_id -cne "phoenix-harness-eval-preregistration-v1" -or
    $Protocol.protocol_status -cne "preregistered" -or
    $Protocol.execution_status -cne "not_run") {
    Fail "unsupported protocol"
}

$RequiredPins = @(
    "phoenix_source_commit", "phoenix_build_stamp", "model_id", "runner_version",
    "environment_manifest_hash", "task_set_hash", "seeds",
    "level_1_sealed_verifier_hash", "level_2_adversarial_verifier_hash"
)
if (-not (Test-ExactProperties $Protocol.pinning $RequiredPins)) {
    Fail "protocol pins are incomplete"
}
$SeedPin = $Protocol.pinning.seeds
if (-not (Test-ExactProperties $SeedPin @("values", "state", "immutable_during_run")) -or
    $SeedPin.state -cne "preregistered_fixed" -or
    $SeedPin.immutable_during_run -isnot [bool] -or
    -not $SeedPin.immutable_during_run -or
    (Get-CanonicalJson @($SeedPin.values)) -cne (Get-CanonicalJson $DefaultSeeds)) {
    Fail "protocol seeds are invalid"
}
foreach ($Name in @($RequiredPins | Where-Object { $_ -ne "seeds" })) {
    $Pin = $Protocol.pinning.PSObject.Properties[$Name].Value
    if (-not (Test-ExactProperties $Pin @(
                "value", "state", "replace_before", "immutable_during_run"
            )) -or
        $Pin.value -isnot [string] -or [string]::IsNullOrWhiteSpace($Pin.value) -or
        $Pin.immutable_during_run -isnot [bool] -or -not $Pin.immutable_during_run -or
        $Pin.replace_before -cne "first_benchmark_run") {
        Fail "protocol pin is invalid"
    }
    $IsPlaceholder = $Pin.value.StartsWith("PREREGISTRATION_PLACEHOLDER:")
    if (($IsPlaceholder -and $Pin.state -cne "preregistration_placeholder") -or
        (-not $IsPlaceholder -and $Pin.state -cne "pinned")) {
        Fail "protocol pin is invalid"
    }
}

$Execution = $Protocol.execution
if (-not (Test-ExactProperties $Execution @(
            "arms", "min_repetitions", "repetitions_per_task", "pairing", "order"
        )) -or
    (Get-CanonicalJson @($Execution.arms)) -cne (Get-CanonicalJson @("phoenix", "control")) -or
    $Execution.min_repetitions -ne 5 -or $Execution.repetitions_per_task -ne 5 -or
    -not (Test-ExactProperties $Execution.pairing @(
            "unit", "same_task_required", "same_seed_required",
            "one_run_per_arm_required", "drop_incomplete_pairs"
        )) -or
    (Get-CanonicalJson @($Execution.pairing.unit)) -cne (
        Get-CanonicalJson @("task_id", "seed")
    ) -or
    @($Execution.pairing.same_task_required,
        $Execution.pairing.same_seed_required,
        $Execution.pairing.one_run_per_arm_required,
        $Execution.pairing.drop_incomplete_pairs) -contains $false -or
    -not (Test-ExactProperties $Execution.order @(
            "policy", "derivation", "arm_state_isolation_required"
        )) -or
    $Execution.order.policy -cne "deterministic_counterbalanced" -or
    $Execution.order.derivation -cne "sha256(task_id || seed) parity" -or
    $Execution.order.arm_state_isolation_required -ne $true) {
    Fail "protocol execution shape is invalid"
}
if ($Protocol.mocks.classification -cne "mechanics_only" -or
    $Protocol.mocks.performance_evidence_allowed -ne $false -or
    $Protocol.mocks.included_in_metrics -ne $false -or
    $Protocol.evidence.performance_claims_allowed -ne $false -or
    @($Protocol.evidence.benchmark_results).Count -ne 0) {
    Fail "protocol evidence shape is invalid"
}
$EvaluatorChecks = @($Protocol.checks.evaluator_only)
if ($EvaluatorChecks.Count -ne 2 -or
    @($EvaluatorChecks | Where-Object {
            $_.visibility -cne "evaluator_only" -or $_.exposed_to_agent -ne $false
        }).Count -ne 0 -or
    @($EvaluatorChecks.level | Sort-Object) -join "," -cne
        "level_1_sealed,level_2_adversarial") {
    Fail "protocol verifier shape is invalid"
}
if (-not $MechanicsOnly -and [string]::IsNullOrWhiteSpace($env:PHOENIX_BUILD_STAMP)) {
    Fail "PHOENIX_BUILD_STAMP is required for a production run"
}

try {
    $SourceCommit = (& git -C $RepoRoot rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
} catch { $SourceCommit = "" }
if ($SourceCommit -notmatch "^[0-9a-fA-F]{40}$") { Fail "full git source commit unavailable" }
$BuildStamp = if ($env:PHOENIX_BUILD_STAMP) { $env:PHOENIX_BUILD_STAMP } else { "mechanics-only-fake" }
if ($BuildStamp -match "PREREGISTRATION_PLACEHOLDER") { Fail "placeholder build stamp refused" }

$PythonVersion = (& python -c "import platform; print(platform.python_version())").Trim()
$PytestVersion = (& python -c "import pytest; print(pytest.__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or $PythonVersion -notmatch "^\d+\.\d+\.\d+" -or
    $PytestVersion -notmatch "^\d+\.\d+") {
    Fail "runtime dependency inspection failed"
}
$ExecutionPolicy = if ($env:PSExecutionPolicyPreference) {
    $env:PSExecutionPolicyPreference
} else {
    "process-default"
}
$Environment = [ordered]@{
    os = [Environment]::OSVersion.Platform.ToString()
    os_version = [Environment]::OSVersion.Version.ToString()
    architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    powershell = $PSVersionTable.PSVersion.ToString()
    python = $PythonVersion
    dependencies = [ordered]@{
        pytest = $PytestVersion
    }
    resource_limits = [ordered]@{
        enforcement = "none"
        windows_job_object = "not_configured"
        process_memory = "os_managed"
        cpu_time = "os_managed"
        processor_count = [Environment]::ProcessorCount
    }
    execution_policy = $ExecutionPolicy
}
$EnvironmentHash = Get-Sha256Text (Get-CanonicalJson $Environment)

$TaskManifest = @()
foreach ($Task in $Tasks) {
    $Files = [ordered]@{}
    foreach ($Name in @("problem.md", "solution.py", "test_f2p.py", "test_p2p.py")) {
        $Files[$Name] = Get-FileSha256 (Join-Path $Task.FullName $Name)
    }
    $TaskManifest += [ordered]@{ task_id = $Task.Name; files = $Files }
}
$TaskSetHash = Get-Sha256Text (Get-CanonicalJson $TaskManifest)
$RunnerSha = Get-FileSha256 $RunnerPath

$HashOutput = & python $Verifier --hash-report 2>$null
if ($LASTEXITCODE -ne 0) { Fail "verifier hash report failed" }
try { $VerifierHashes = ($HashOutput -join "`n") | ConvertFrom-Json }
catch { Fail "verifier hash report is malformed" }
if (-not (Test-ExactProperties $VerifierHashes @("level1_sealed", "level2_adversarial")) -or
    $VerifierHashes.level1_sealed -notmatch "^[0-9a-f]{64}$" -or
    $VerifierHashes.level2_adversarial -notmatch "^[0-9a-f]{64}$") {
    Fail "verifier hash report is malformed"
}

$ComputedPins = [ordered]@{
    phoenix_source_commit = $SourceCommit
    phoenix_build_stamp = $BuildStamp
    model_id = $Model
    runner_version = $RunnerVersion
    environment_manifest_hash = $EnvironmentHash
    task_set_hash = $TaskSetHash
    level_1_sealed_verifier_hash = "sha256:$($VerifierHashes.level1_sealed)"
    level_2_adversarial_verifier_hash = "sha256:$($VerifierHashes.level2_adversarial)"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$RawPath = Join-Path $OutputDir "raw-runs.jsonl"
$ManifestPath = Join-Path $OutputDir "run-manifest.json"
try {
    $OutputLock = [IO.File]::Open(
        "$ManifestPath.lock",
        [IO.FileMode]::OpenOrCreate,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
} catch [IO.IOException] {
    Fail "another harness phase is active for this output"
}

$PinnedValues = [ordered]@{
    phoenix_source_commit = [ordered]@{ state = "pinned"; value = $ComputedPins.phoenix_source_commit }
    phoenix_build_stamp = [ordered]@{ state = "pinned"; value = $ComputedPins.phoenix_build_stamp }
    model_id = [ordered]@{ state = "pinned"; value = $ComputedPins.model_id }
    runner_version = [ordered]@{ state = "pinned"; value = $ComputedPins.runner_version }
    environment_manifest_hash = [ordered]@{ state = "pinned"; value = $ComputedPins.environment_manifest_hash }
    task_set_hash = [ordered]@{ state = "pinned"; value = $ComputedPins.task_set_hash }
    seeds = [ordered]@{ state = "pinned"; values = @($Seeds) }
    level_1_sealed_verifier_hash = [ordered]@{
        state = "pinned"; value = $ComputedPins.level_1_sealed_verifier_hash
    }
    level_2_adversarial_verifier_hash = [ordered]@{
        state = "pinned"; value = $ComputedPins.level_2_adversarial_verifier_hash
    }
    runner_hash = $RunnerSha
    runner_sha256 = $RunnerSha
}
$FrozenManifest = [ordered]@{
    schema_version = "1.0"
    protocol_id = $Protocol.protocol_id
    protocol_status = $Protocol.protocol_status
    execution_status = "frozen"
    evidence_classification = if ($MechanicsOnly) { "mechanics_only" } else { "benchmark" }
    tasks = @($Tasks.Name)
    environment = $Environment
    pins = $PinnedValues
    task_manifest = $TaskManifest
    run_count = 0
}

if ($FreezePins) {
    if ((Test-Path -LiteralPath $PinnedProtocolFile) -or
        (Test-Path -LiteralPath $ManifestPath) -or
        (Test-Path -LiteralPath $RawPath)) {
        if (-not $Force) { Fail "frozen output exists; use -Force to overwrite" }
        Remove-Item -LiteralPath $PinnedProtocolFile, $ManifestPath, $RawPath `
            -Force -ErrorAction SilentlyContinue
    }
    $PinnedProtocol = (Get-CanonicalJson $Protocol) | ConvertFrom-Json
    foreach ($Name in $ComputedPins.Keys) {
        $PinnedProtocol.pinning.PSObject.Properties[$Name].Value.value = $ComputedPins[$Name]
        $PinnedProtocol.pinning.PSObject.Properties[$Name].Value.state = "pinned"
    }
    $PinnedProtocol.pinning.seeds.values = @($Seeds)
    $PinnedProtocol.pinning.seeds.state = "pinned"
    Write-JsonAtomic $PinnedProtocolFile $PinnedProtocol
    Write-JsonAtomic $ManifestPath $FrozenManifest
    $OutputLock.Dispose()
    Write-Output "FROZEN: production pins written; no runs executed"
    exit 0
}

if ($MechanicsOnly) {
    if (-not (Test-Path -LiteralPath $CopilotCommand -PathType Leaf)) {
        Fail "Copilot command is missing"
    }
    if ((Test-Path -LiteralPath $RawPath) -or (Test-Path -LiteralPath $ManifestPath)) {
        if (-not $Force) { Fail "output exists; use -Force to overwrite" }
        Remove-Item -LiteralPath $RawPath, $ManifestPath -Force -ErrorAction SilentlyContinue
    }
    $Manifest = $FrozenManifest
    $Manifest.execution_status = "mechanics_only"
    Write-JsonAtomic $ManifestPath $Manifest
} else {
    if (-not (Test-Path -LiteralPath $PinnedProtocolFile -PathType Leaf)) {
        Fail "pinned protocol is required; run production phase A with -FreezePins"
    }
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        Fail "frozen run manifest is required; run production phase A with -FreezePins"
    }
    if (Test-Path -LiteralPath $RawPath) {
        Fail "raw output already exists; freeze a new production run"
    }
    try {
        $PinnedProtocol = Get-Content -LiteralPath $PinnedProtocolFile -Raw | ConvertFrom-Json
        $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    } catch {
        Fail "frozen production artifacts are malformed"
    }
    $ExpectedPinnedProtocol = (Get-CanonicalJson $Protocol) | ConvertFrom-Json
    foreach ($Name in $ComputedPins.Keys) {
        $ExpectedPinnedProtocol.pinning.PSObject.Properties[$Name].Value.value = $ComputedPins[$Name]
        $ExpectedPinnedProtocol.pinning.PSObject.Properties[$Name].Value.state = "pinned"
    }
    $ExpectedPinnedProtocol.pinning.seeds.values = @($Seeds)
    $ExpectedPinnedProtocol.pinning.seeds.state = "pinned"
    if ((Get-CanonicalJson $PinnedProtocol) -cne (Get-CanonicalJson $ExpectedPinnedProtocol)) {
        Fail "pinned protocol does not exactly match current production inputs"
    }
    if ((Get-CanonicalJson $Manifest) -cne (Get-CanonicalJson $FrozenManifest)) {
        Fail "frozen run manifest does not exactly match current production inputs"
    }
    if (-not (Test-Path -LiteralPath $CopilotCommand -PathType Leaf)) {
        Fail "Copilot command is missing"
    }
    $Manifest.execution_status = "running"
    Write-JsonAtomic $ManifestPath $Manifest
}

$Seen = @{}
$CompletedRows = 0
foreach ($Task in $Tasks) {
    $Problem = Get-Content -LiteralPath (Join-Path $Task.FullName "problem.md") -Raw
    foreach ($Seed in $Seeds) {
        $PairKey = "$($Task.Name)|$Seed"
        $Digest = Get-Sha256Text "$($Task.Name)$Seed"
        $Parity = [Convert]::ToInt32($Digest.Substring($Digest.Length - 2), 16) % 2
        $Arms = if ($Parity -eq 0) { @("control", "phoenix") } else { @("phoenix", "control") }
        foreach ($Arm in $Arms) {
            $RunKey = "$PairKey|$Arm"
            if ($Seen.ContainsKey($RunKey)) { Fail "duplicate run detected" }
            $Seen[$RunKey] = $true
            $Workspace = Join-Path ([IO.Path]::GetTempPath()) (
                "phoenix_harness_{0}_{1}" -f $Task.Name, [guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Path $Workspace | Out-Null
            try {
                Copy-Item -LiteralPath (Join-Path $Task.FullName "problem.md") -Destination $Workspace
                Copy-Item -LiteralPath (Join-Path $Task.FullName "solution.py") -Destination $Workspace
                if ($Arm -eq "phoenix") {
                    Copy-Item -LiteralPath (Join-Path $Task.FullName "test_f2p.py") -Destination $Workspace
                    Copy-Item -LiteralPath (Join-Path $Task.FullName "test_p2p.py") -Destination $Workspace
                    $Prompt = "Task $($Task.Name), seed $Seed. Read problem.md and fix solution.py without changing its public API or tests. Use the phoenix MCP tools. You must call phoenix_sense with the public gate 'python -m pytest test_f2p.py test_p2p.py -q' and require exit 0 before claiming completion. Do not edit tests. End with DONE only after the public gate is green."
                } else {
                    $Prompt = "Task $($Task.Name), seed $Seed. Read problem.md and fix solution.py without changing its public API. End with DONE only when confident the described behavior is correct."
                }
                $Arguments = @("-p", $Prompt, "--model", $Model, "-C", $Workspace,
                    "--no-custom-instructions", "--no-remote", "--no-remote-export",
                    "--no-auto-update", "--output-format", "json", "--allow-all-tools",
                    "--add-dir", $Workspace)
                if ($Arm -eq "control") { $Arguments += @("--disable-mcp-server", "phoenix") }
                $Started = [DateTime]::UtcNow.ToString("o")
                $PreviousErrorActionPreference = $ErrorActionPreference
                try {
                    $ErrorActionPreference = "Continue"
                    $Transcript = (& $CopilotCommand @Arguments 2>&1 | Out-String)
                    $ExitCode = $LASTEXITCODE
                    if ($null -eq $ExitCode) { $ExitCode = 0 }
                } catch {
                    Fail "Copilot command could not be started"
                } finally {
                    $ErrorActionPreference = $PreviousErrorActionPreference
                }
                $Ended = [DateTime]::UtcNow.ToString("o")
                $ClaimedDone = $Transcript -match "(?im)\bDONE\b"
                $SolutionPath = Join-Path $Workspace "solution.py"
                if (-not (Test-Path -LiteralPath $SolutionPath -PathType Leaf)) {
                    Set-Content -LiteralPath $SolutionPath -Value "" -NoNewline
                }
                $EvaluatedSolutionSha = Get-FileSha256 $SolutionPath
                $VerifyOutput = & python $Verifier --workspace $Workspace `
                    --task-id $Task.Name 2>$null
                if ($LASTEXITCODE -ne 0 -or $null -eq $VerifyOutput) {
                    Fail "verifier process failed"
                }
                try { $Verification = ($VerifyOutput -join "`n") | ConvertFrom-Json }
                catch { Fail "verifier JSON is malformed" }
                if (-not (Test-ExactProperties $Verification @("level1", "level2")) -or
                    -not (Test-VerificationLevel $Verification.level1 "objective checks failed") -or
                    -not (Test-VerificationLevel $Verification.level2 "adversarial checks failed")) {
                    Fail "verifier JSON is malformed"
                }
                $Objective = $Verification.level1.pass -and $Verification.level2.pass
                $Record = [ordered]@{
                    run_id = [guid]::NewGuid().ToString("N")
                    task_id = $Task.Name; seed = $Seed; arm = $Arm
                    order = [Array]::IndexOf($Arms, $Arm)
                    started_utc = $Started; completed_utc = $Ended
                    exit_code = [int]$ExitCode; claimed_done = [bool]$ClaimedDone
                    model_id = $Model
                    runner_sha256 = $RunnerSha
                    prompt_sha256 = Get-Sha256Text $Prompt
                    transcript_sha256 = Get-Sha256Text $Transcript
                    final_solution_sha256 = $EvaluatedSolutionSha
                    cost_units = 1
                    level1_pass = [bool]$Verification.level1.pass
                    level2_pass = [bool]$Verification.level2.pass
                    objective_pass = [bool]$Objective
                    mock_run = [bool]$MechanicsOnly
                }
                Write-Utf8NoBom $RawPath (Get-CanonicalJson $Record) $true
                $CompletedRows++
            } finally {
                Remove-Item -LiteralPath $Workspace -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

$ExpectedRows = $Tasks.Count * $Seeds.Count * 2
if ($CompletedRows -ne $ExpectedRows -or $Seen.Count -ne $ExpectedRows) {
    Fail "incomplete arm pairs"
}
try {
    $Rows = @(Get-Content -LiteralPath $RawPath | ForEach-Object { $_ | ConvertFrom-Json })
} catch {
    Fail "raw run records are malformed"
}
$RecordFields = @(
    "run_id", "task_id", "seed", "arm", "order", "started_utc", "completed_utc",
    "exit_code", "claimed_done", "model_id", "runner_sha256", "prompt_sha256",
    "transcript_sha256", "final_solution_sha256", "cost_units", "level1_pass",
    "level2_pass", "objective_pass", "mock_run"
)
$ValidatedRuns = @{}
$ValidatedRunIds = @{}
foreach ($Row in $Rows) {
    $Key = "$($Row.task_id)|$($Row.seed)|$($Row.arm)"
    if (-not (Test-ExactProperties $Row $RecordFields) -or
        $Row.task_id -notin @($Tasks.Name) -or $Row.seed -notin $Seeds -or
        $Row.arm -notin @("control", "phoenix") -or $Row.order -notin @(0, 1) -or
        $Row.claimed_done -isnot [bool] -or $Row.level1_pass -isnot [bool] -or
        $Row.level2_pass -isnot [bool] -or $Row.objective_pass -isnot [bool] -or
        $Row.mock_run -isnot [bool] -or $Row.mock_run -ne $MechanicsOnly -or
        $Row.objective_pass -ne ($Row.level1_pass -and $Row.level2_pass) -or
        $Row.run_id -isnot [string] -or [string]::IsNullOrWhiteSpace($Row.run_id) -or
        $Row.model_id -cne $Model -or $Row.runner_sha256 -cne $RunnerSha -or
        $Row.runner_sha256 -notmatch "^[0-9a-f]{64}$" -or
        $Row.prompt_sha256 -notmatch "^[0-9a-f]{64}$" -or
        $Row.transcript_sha256 -notmatch "^[0-9a-f]{64}$" -or
        $Row.final_solution_sha256 -notmatch "^[0-9a-f]{64}$" -or
        $ValidatedRuns.ContainsKey($Key) -or $ValidatedRunIds.ContainsKey($Row.run_id)) {
        Fail "incomplete or duplicate arm pairs"
    }
    $ValidatedRuns[$Key] = $true
    $ValidatedRunIds[$Row.run_id] = $true
}
$Groups = @($Rows | Group-Object { "$($_.task_id)|$($_.seed)" })
if ($Rows.Count -ne $ExpectedRows -or $ValidatedRuns.Count -ne $ExpectedRows -or
    $Groups.Count -ne ($Tasks.Count * $Seeds.Count) -or
    @($Groups | Where-Object {
            $_.Count -ne 2 -or
            (@($_.Group.arm | Sort-Object) -join ",") -cne "control,phoenix" -or
            (@($_.Group.order | Sort-Object) -join ",") -cne "0,1"
        }).Count -ne 0) {
    Fail "incomplete or duplicate arm pairs"
}

$CompletionUtc = [DateTime]::UtcNow.ToString("o")
$Status = if ($MechanicsOnly) { "mechanics_only" } else { "completed" }
$Manifest.execution_status = $Status
$Manifest.run_count = $CompletedRows
Set-ObjectProperty $Manifest.pins "raw_jsonl_hash" (Get-FileSha256 $RawPath)
Set-ObjectProperty $Manifest.pins "completion_utc" $CompletionUtc
Write-JsonAtomic $ManifestPath $Manifest
$OutputLock.Dispose()
Write-Output "DONE: $CompletedRows runs; status=$Status"
