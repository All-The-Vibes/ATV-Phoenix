#requires -Version 5.1
<#
.SYNOPSIS
  ATV-Phoenix x OKF - a self-contained, narrated, end-to-end demo for a live audience.

.DESCRIPTION
  Tells the whole Open Knowledge Format story on real artifacts, with real output:

    BEAT 1  PRODUCE   an opaque code graph becomes a directory of readable markdown concepts
    BEAT 2  VALIDATE  an objective conformance gate (exit 0 == CONFORMANT)
    BEAT 3  SENSE+HEAL the REAL phoenix-mcp spine: green -> inject fault -> RED -> heal -> green,
                       proven red->green in a tamper-evident trace (accept + verify-trace)
    BEAT 4  CONSUME   index-first ingest answers a real structural question cheaply
    BEAT 5  INTEROP   a FOREIGN, hand-authored OKF bundle validates + ingests with zero changes

  Non-destructive: all mutation happens in demo/okf/.work (gitignored). Nothing in the repo is
  touched. Deterministic: no model is called.

.PARAMETER NoPause
  Run start-to-finish without waiting for <enter> between beats (good for recording).
#>
param([switch]$NoPause)

$ErrorActionPreference = 'Stop'
$repo     = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$py       = 'python'
$mcp      = Join-Path $repo 'target\release\phoenix-mcp.exe'
if (-not (Test-Path $mcp)) { $mcp = Join-Path $repo 'target\debug\phoenix-mcp.exe' }
$scripts  = Join-Path $repo 'skills\phoenix-okf\scripts'
$validate = Join-Path $scripts 'okf_validate.py'
$ingest   = Join-Path $scripts 'okf_ingest.py'
$export   = Join-Path $scripts 'okf_export.py'
$graph    = Join-Path $repo '.token-master\graph.json'
$external = Join-Path $repo 'examples\okf-external-demo'
$work     = Join-Path $PSScriptRoot '.work'
$bundle   = Join-Path $work 'bundle'
$concept  = 'concepts/src/heal.rs.md'   # the file we will fault + heal (bundle-relative)

function Beat([int]$n, [string]$t) {
  Write-Host ''
  Write-Host ('=' * 78) -ForegroundColor Cyan
  Write-Host ("  BEAT $n  $t") -ForegroundColor Cyan
  Write-Host ('=' * 78) -ForegroundColor Cyan
}
function Note([string]$s) { Write-Host "  $s" -ForegroundColor DarkGray }
function Ok([string]$s)   { Write-Host "  [GREEN] $s" -ForegroundColor Green }
function Bad([string]$s)  { Write-Host "  [RED]   $s" -ForegroundColor Red }
function Hold {
  if (-not $NoPause) { Write-Host ''; Read-Host '  -- press <enter> for the next beat --' | Out-Null }
}
function Run([string]$exe, [string[]]$argv) {
  # Run a tool, stream its output indented, and return @{ code; out }.
  $out = & $exe @argv 2>&1 | Out-String
  ($out.TrimEnd() -split "`n") | ForEach-Object { Write-Host "    $_" }
  return @{ code = $LASTEXITCODE; out = $out }
}

Write-Host ''
Write-Host '  ATV-Phoenix x Open Knowledge Format - knowledge that pays rent in the open' -ForegroundColor White
Write-Host '  --------------------------------------------------------------------------'
Note 'OKF v0.1 = a directory of markdown concepts with YAML frontmatter (one required key: type).'
Note 'Phoenix produces it, validates it, SENSES + HEALS it through the spine, and consumes it cheap.'

# Fresh scratch.
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force -Path $work | Out-Null

# ---------------------------------------------------------------------------------------------
Beat 1 'PRODUCE - opaque graph.json  ->  browsable OKF bundle'
if (Test-Path $graph) {
  Note 'Exporting the live code graph to an OKF bundle...'
  Run $py @($export, '--graph', $graph, '--out', $bundle, '--name', 'ATV-Phoenix') | Out-Null
} else {
  Note 'No live graph.json on this machine - using the committed exported bundle instead.'
  Copy-Item -Recurse (Join-Path $repo 'examples\okf-code-graph') $bundle
}
$nConcepts = (Get-ChildItem -Recurse -Filter *.md $bundle | Where-Object { $_.Name -notin @('index.md','log.md') }).Count
Ok "Produced $nConcepts concept documents - a plain directory you can cat, git diff, and Obsidian-browse."
Note 'Top of the bundle:'
Get-ChildItem $bundle | Select-Object -First 6 Name | ForEach-Object { Write-Host "    $($_.Name)" }
Note "One concept (${concept}), first lines - note the human-readable frontmatter + relationships:"
Get-Content (Join-Path $bundle ($concept -replace '/','\')) -TotalCount 12 | ForEach-Object { Write-Host "    $_" }
Hold

# ---------------------------------------------------------------------------------------------
Beat 2 'VALIDATE - the objective conformance gate'
$r = Run $py @($validate, $bundle)
if ($r.code -eq 0) { Ok 'CONFORMANT with OKF v0.1 (exit 0). This exit code IS the phoenix_sense gate.' }
else { Bad 'NON-CONFORMANT - demo bundle is broken.'; exit 1 }
Hold

# ---------------------------------------------------------------------------------------------
Beat 3 'SENSE + HEAL - knowledge is a self-healing artifact (real phoenix-mcp spine)'
Note "Spine binary: $mcp"
$env:PHOENIX_WORKSPACE = $bundle    # isolate the trace + resolve paths inside the scratch bundle
$check   = Join-Path $work 'check.json'
$healctx = Join-Path $work 'healctx.json'
# A command_exit check: 'is the bundle OKF-conformant?' - absolute paths so it is cwd-independent.
$checkObj = [ordered]@{ kind = 'command_exit'; target = @($py, $validate, $bundle); expect = 0 }
[System.IO.File]::WriteAllText($check, ($checkObj | ConvertTo-Json -Compress))

Note '1) sense the conformance check - expect GREEN:'
$s = Run $mcp @('sense', "@$check")
if ($s.code -ne 0) { Bad 'baseline should be green'; exit 1 }
Ok 'baseline GREEN.'

Note '2) snapshot the concept as last-good (blessed ONLY because the check is green):'
$snapRaw = & $mcp snapshot $concept "@$check" 2>&1 | Out-String
$snap = $snapRaw | ConvertFrom-Json
$snapId = $snap.snap_id
Ok "blessed snapshot: $snapId"

Note "3) inject a behavioral fault - strip the required type line from ${concept}:"
$victim = Join-Path $bundle ($concept -replace '/','\')
(Get-Content $victim) | Where-Object { $_ -notmatch '^type:\s' } | Set-Content -Encoding utf8 $victim
Bad 'fault injected (concept now has no type field).'

Note '4) sense again - expect RED (the spine catches the rot objectively):'
$s = Run $mcp @('sense', "@$check")
if ($s.code -eq 0) { Bad 'fault not detected'; exit 1 }
Bad 'RED - conformance broke, exactly as it should.'

Note '5) heal by bounded rollback to the blessed snapshot; recovery validated by the SAME check:'
$healObj = [ordered]@{ path = $concept; snap_id = $snapId; recheck = $checkObj }
[System.IO.File]::WriteAllText($healctx, ($healObj | ConvertTo-Json -Depth 6 -Compress))
$h = Run $mcp @('heal', 'rollback', "@$healctx")
if ($h.code -ne 0) { Bad 'heal failed'; exit 1 }
Ok 'healed.'

Note '6) sense once more - expect GREEN again:'
$s = Run $mcp @('sense', "@$check")
if ($s.code -ne 0) { Bad 'still red after heal'; exit 1 }
Ok 'GREEN again.'

Note '7) accept - prove from the tamper-evident trace that THIS check went red->green (failure-first):'
$a = Run $mcp @('accept', "@$check")
if ($a.code -ne 0) { Bad 'accept did not confirm red->green'; exit 1 }
Ok 'accept ok=true - red->green is PROVEN, not asserted.'

Note '8) verify-trace - the hash chain is intact:'
$v = Run $mcp @('verify-trace')
if ($v.code -ne 0) { Bad 'trace broken'; exit 1 }
Ok 'trace verified. A knowledge bundle that drifts now emits an objective RED a run can heal.'
Remove-Item Env:\PHOENIX_WORKSPACE
Hold

# ---------------------------------------------------------------------------------------------
Beat 4 'CONSUME - index-first, pay once to orient'
Note 'Real structural question: "what cross-file edges does src/heal.rs have, and what does it define?"'
Note 'a. index-first outline (cheap, paid ONCE per session):'
Run $py @($ingest, $bundle, '--max', '6') | Out-Null
Note "b. open EXACTLY the one concept that answers it (${concept}):"
Run $py @($ingest, $bundle, '--full', $concept) | Out-Null
Ok 'Answer read straight off the frontmatter + Relationships - no whole-directory dump.'
Note 'Measured token efficiency (tiktoken o200k_base) lives in evals/m4-okf and evals/m5-okf-live:'
Note '  index-first vs raw graph.json = 31.3x fewer tokens; session view beats grep 2.1x.'
Hold

# ---------------------------------------------------------------------------------------------
Beat 5 'INTEROP - a FOREIGN bundle Phoenix never produced'
Note 'examples/okf-external-demo was hand-authored by "acme-knowledge-catalog" with a NON-Phoenix'
Note 'vocabulary (Runbook / Dataset / Decision / Glossary). Same gate + consumer, zero changes:'
$r = Run $py @($validate, $external, '--strict-links')
if ($r.code -ne 0) { Bad 'external bundle failed'; exit 1 }
Ok 'Foreign bundle CONFORMANT (even --strict-links). OKF is vendor-neutral, and so is Phoenix.'
Run $py @($ingest, $external) | Out-Null
Hold

Write-Host ''
Write-Host ('=' * 78) -ForegroundColor White
Write-Host '  THE STORY: Phoenix PRODUCES open knowledge, GATES it, SENSES + HEALS it like code,' -ForegroundColor White
Write-Host '  CONSUMES it cheaply, and INTEROPS with anyone elses OKF bundle. Knowledge is now a' -ForegroundColor White
Write-Host '  first-class, self-healing, vendor-neutral artifact - not an opaque blob.' -ForegroundColor White
Write-Host ('=' * 78) -ForegroundColor White
Write-Host ''
Note 'Re-run anytime: pwsh demo/okf/run-demo.ps1   (add -NoPause to record straight through).'
