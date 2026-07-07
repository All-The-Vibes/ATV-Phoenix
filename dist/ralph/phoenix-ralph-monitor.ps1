<#
.SYNOPSIS
  phoenix-ralph-monitor.ps1 -- snapshot the objective state of a phoenix-ralph run.

.DESCRIPTION
  Reads .phoenix-ralph/ state files and .phoenix/trace.jsonl and prints a concise
  status snapshot to stdout. This is a READ-ONLY tool: it never writes anything.
  All information is derived from the tamper-evident trace and structured state files --
  no self-reporting, no inference.

  Use --once (default) for a single snapshot in CI or shell pipelines.
  Use --follow to auto-refresh every RefreshSecs seconds (Ctrl-C to stop).
  Use --json to emit machine-readable JSON instead of the formatted table.

.PARAMETER Dir
  Path to the .phoenix-ralph state directory. Default: .phoenix-ralph in cwd.

.PARAMETER PhoenixBin
  Path to phoenix-mcp binary. Auto-detected from target/release/ or PATH if omitted.

.PARAMETER Once
  Print one snapshot and exit. Default: true when not using --follow.

.PARAMETER Follow
  Loop and refresh every RefreshSecs seconds. Ctrl-C to stop.

.PARAMETER RefreshSecs
  Auto-refresh interval when using --follow. Default: 2.

.PARAMETER Json
  Emit machine-readable JSON instead of formatted output.

.EXAMPLE
  pwsh -File phoenix-ralph-monitor.ps1
  pwsh -File phoenix-ralph-monitor.ps1 --follow
  pwsh -File phoenix-ralph-monitor.ps1 --dir /path/to/project/.phoenix-ralph --json
#>
[CmdletBinding()]
param(
    [string]$Dir         = ".phoenix-ralph",
    [string]$PhoenixBin  = "",
    [switch]$Once,
    [switch]$Follow,
    [int]$RefreshSecs    = 2,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

# ---- locate binaries ----
function Find-Phoenix {
    $repo = (Get-Location).Path
    $cands = @(
        "$repo\target\release\phoenix-mcp.exe",
        "$repo\target\debug\phoenix-mcp.exe"
    ) | Where-Object { Test-Path $_ }
    if ($cands) { return $cands | Select-Object -First 1 }
    if (Get-Command phoenix-mcp -ErrorAction SilentlyContinue) { return "phoenix-mcp" }
    return $null
}

if (-not $PhoenixBin) { $PhoenixBin = Find-Phoenix }

# ---- helpers ----
function Read-JsonFile($path) {
    if (-not (Test-Path $path)) { return $null }
    try {
        $raw = [System.IO.File]::ReadAllBytes($path)
        if ($raw.Length -ge 3 -and $raw[0] -eq 0xEF) { $raw = $raw[3..($raw.Length-1)] }
        return [System.Text.Encoding]::UTF8.GetString($raw) | ConvertFrom-Json
    } catch { return $null }
}

function Count-TraceEvents($tracePath) {
    if (-not (Test-Path $tracePath)) { return 0 }
    return (Get-Content $tracePath -ErrorAction SilentlyContinue | Measure-Object).Count
}

function Get-SnapshotData($repo, $dir) {
    $state     = Join-Path $repo $dir
    $tracePath = Join-Path $repo ".phoenix\trace.jsonl"

    $backlog    = Read-JsonFile (Join-Path $state "backlog.json")
    $doneCheck  = Read-JsonFile (Join-Path $state "done-check.json")
    $completed  = Read-JsonFile (Join-Path $state "completed.json")
    $driverLog  = Join-Path $state "driver.log"

    # Parse driver.log for loop counter and no-progress counter
    $loop = $null; $noProgress = $null; $maxLoops = $null
    if (Test-Path $driverLog) {
        $logLines = Get-Content $driverLog -ErrorAction SilentlyContinue
        $lastLoop = $logLines | Select-String "iteration (\d+)/(\d+)" | Select-Object -Last 1
        if ($lastLoop) {
            $loop     = [int]$lastLoop.Matches[0].Groups[1].Value
            $maxLoops = [int]$lastLoop.Matches[0].Groups[2].Value
        }
        $lastNP = $logLines | Select-String "no state change \((\d+)/" | Select-Object -Last 1
        if ($lastNP) { $noProgress = [int]$lastNP.Matches[0].Groups[1].Value } else { $noProgress = 0 }
    }

    # Backlog stats
    $backlogTotal = 0; $backlogDone = 0; $currentItem = $null
    if ($backlog) {
        $backlogTotal = @($backlog).Count
        $backlogDone  = @($backlog | Where-Object { $_.done -eq $true }).Count
        $currentItem  = $backlog | Where-Object { $_.done -eq $false } | Select-Object -First 1
    }

    # Trace stats + last sense
    $traceCount = Count-TraceEvents $tracePath
    $lastSense  = $null; $traceIntact = $null
    if ($PhoenixBin -and (Test-Path $tracePath)) {
        # verify-trace is cheap (read-only hash check)
        $vt = & $PhoenixBin verify-trace 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($vt) { $traceIntact = $vt.ok }
        # last sense event
        $lastLine = Get-Content $tracePath -ErrorAction SilentlyContinue | Select-Object -Last 1
        if ($lastLine) {
            try { $lastSense = $lastLine | ConvertFrom-Json } catch {}
        }
    }

    # Accept verdict (done-check gate)
    $acceptResult = $null
    if ($PhoenixBin -and $doneCheck) {
        $tmpChk = [System.IO.Path]::GetTempFileName() + ".json"
        try {
            $doneCheck | ConvertTo-Json -Depth 5 -Compress | Set-Content -Encoding UTF8 $tmpChk
            $ar = & $PhoenixBin accept "@$tmpChk" 2>$null
            if ($ar) { try { $acceptResult = $ar | ConvertFrom-Json } catch {} }
        } finally { Remove-Item $tmpChk -ErrorAction SilentlyContinue }
    }

    return [ordered]@{
        state_dir       = $state
        trace_path      = $tracePath
        is_complete     = ($completed -ne $null)
        loop            = $loop
        max_loops       = $maxLoops
        no_progress     = $noProgress
        backlog_total   = $backlogTotal
        backlog_done    = $backlogDone
        current_item    = if ($currentItem) { $currentItem.title } else { $null }
        trace_events    = $traceCount
        trace_intact    = $traceIntact
        last_sense_ok   = if ($lastSense) { $lastSense.ok } else { $null }
        last_sense_sig  = if ($lastSense) { $lastSense.signal } else { $null }
        last_sense_ts   = if ($lastSense) { $lastSense.ts } else { $null }
        accept_ok           = if ($acceptResult) { $acceptResult.ok }            else { $null }
        accept_saw_red      = if ($acceptResult) { $acceptResult.saw_red }       else { $null }
        accept_green_after  = if ($acceptResult) { $acceptResult.green_after_red } else { $null }
        accept_trace_intact = if ($acceptResult) { $acceptResult.trace_intact }  else { $null }
    }
}

function Format-Snapshot($s) {
    $state  = if ($s.is_complete) { "COMPLETE" } elseif ($s.loop) { "RUNNING" } else { "IDLE" }
    $loop   = if ($s.loop)      { "$($s.loop)/$($s.max_loops)" } else { "--" }
    $noProg = if ($s.no_progress -ne $null) { "$($s.no_progress)" } else { "--" }
    $bl     = "$($s.backlog_done)/$($s.backlog_total)"
    $cur    = if ($s.current_item) { $s.current_item } else { "(none)" }
    $ti     = if ($s.trace_intact -eq $true) { "INTACT" } elseif ($s.trace_intact -eq $false) { "BROKEN" } else { "--" }
    $ls     = if ($s.last_sense_ok -eq $true) { "GREEN" } elseif ($s.last_sense_ok -eq $false) { "RED" } else { "--" }
    $lsSig  = if ($s.last_sense_sig) { $s.last_sense_sig } else { "" }
    $ac     = if ($s.accept_ok -eq $true) { "PROVEN" } elseif ($s.accept_ok -eq $false) { "UNPROVEN" } else { "--" }
    $acSaw  = if ($s.accept_saw_red -ne $null) { "saw_red=$($s.accept_saw_red)" } else { "" }

    $lines = @(
        "phoenix-ralph monitor  state=$state  $(Get-Date -Format 'HH:mm:ss')"
        "  loop        $loop"
        "  no-progress $noProg"
        "  backlog     $bl  current: $cur"
        "  trace       $($s.trace_events) events  chain=$ti"
        "  last sense  $ls  $lsSig"
        "  done-check  $ac  $acSaw"
    )
    return $lines -join "`n"
}

# ---- main ----
$repo = (Get-Location).Path
$continuous = $Follow.IsPresent -and -not $Once.IsPresent

do {
    $snap = Get-SnapshotData $repo $Dir
    if ($Json) {
        $snap | ConvertTo-Json -Depth 5
    } else {
        if ($continuous) { Clear-Host }
        Write-Host (Format-Snapshot $snap)
    }
    if ($continuous) { Start-Sleep -Seconds $RefreshSecs }
} while ($continuous)