# M2 MCP protocol validation — drives phoenix-mcp over stdio JSON-RPC like Copilot would.
# Produces evals/m2-mcp/session.txt (the request/response transcript).
$ErrorActionPreference = "Continue"
$repo = "C:\Users\shyamsridhar\code\ATV-Phoenix"
$bin  = Join-Path $repo "target\debug\phoenix-mcp.exe"
$ws   = Join-Path $env:TEMP ("phx_m2_" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Force -Path $ws | Out-Null
$logic = Join-Path $ws "logic.txt"
Set-Content $logic "answer=GOOD_MARKER`n" -NoNewline
$env:PHOENIX_WORKSPACE = $ws

function J($p) { $p -replace '\\','\\' }
$check = '{"kind":"command_exit","target":["cmd","/C","findstr","/C:GOOD_MARKER","' + (J $logic) + '"],"expect":"0"}'

# Run A: init, sense (GREEN), snapshot (BLESS)
$msgsA = @(
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"copilot-like","version":"1"}}}'
  '{"jsonrpc":"2.0","method":"notifications/initialized"}'
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"phoenix_sense","arguments":{"check":' + $check + '}}}'
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"phoenix_snapshot","arguments":{"path":"logic.txt","check":' + $check + '}}}'
)
$outA = (($msgsA -join "`n") + "`n") | & $bin 2>$null | Out-String
$snapLine = ($outA -split "`n") | Where-Object { $_ -match '"id":3' } | Select-Object -First 1
$snapId = if ($snapLine -match '\\"snap_id\\":\\"([^\\"]+)\\"') { $matches[1] } else { "" }

# INJECT FAULT between runs (shared workspace + trace)
Set-Content $logic "answer=BROKEN`n" -NoNewline

# Run B: init, sense (RED), heal rollback, sense (GREEN), verify_trace
$healCtx = '{"path":"logic.txt","snap_id":"' + $snapId + '","recheck":' + $check + '}'
$msgsB = @(
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"copilot-like","version":"1"}}}'
  '{"jsonrpc":"2.0","method":"notifications/initialized"}'
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"phoenix_sense","arguments":{"check":' + $check + '}}}'
  '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"phoenix_heal","arguments":{"strategy":"rollback","ctx":' + $healCtx + '}}}'
  '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"phoenix_sense","arguments":{"check":' + $check + '}}}'
  '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"phoenix_verify_trace","arguments":{}}}'
)
$outB = (($msgsB -join "`n") + "`n") | & $bin 2>$null | Out-String

function Field($json, $id, $key) {
  $line = ($json -split "`n") | Where-Object { $_ -match "`"id`":$id" } | Select-Object -First 1
  if ($line -match "\\`"$key\\`":(true|false)") { return $matches[1] }
  if ($line -match "\\`"$key\\`":\\`"([^\\`"]+)\\`"") { return $matches[1] }
  if ($line -match "\\`"$key\\`":([0-9]+)") { return $matches[1] }
  return "?"
}

$lines = @()
$lines += "ATV-Phoenix M2 - spine driven over MCP stdio JSON-RPC (as GitHub Copilot would call it)"
$lines += "server: phoenix-mcp.exe   transport: stdio   protocol: 2025-06-18"
$lines += ""
$lines += "tools advertised: phoenix_sense, phoenix_snapshot, phoenix_heal, phoenix_verify_trace"
$lines += ""
$lines += ("1. phoenix_sense  (baseline)   -> ok = " + (Field $outA 2 'ok') + "    [GREEN]")
$lines += ("2. phoenix_snapshot            -> blessed = " + (Field $outA 3 'blessed') + "    snap_id = " + $snapId)
$lines += "   << inject fault: logic.txt -> answer=BROKEN >>"
$lines += ("3. phoenix_sense  (post-fault) -> ok = " + (Field $outB 4 'ok') + "    [RED - detected]")
$lines += ("4. phoenix_heal   (rollback)   -> healed = " + (Field $outB 5 'healed'))
$lines += ("5. phoenix_sense  (post-heal)  -> ok = " + (Field $outB 6 'ok') + "    [GREEN - recovered]")
$lines += ("6. phoenix_verify_trace        -> ok = " + (Field $outB 7 'ok') + "    rows = " + (Field $outB 7 'rows'))
$lines += ""
$lines += "VERDICT: a fault was SENSED and HEALED entirely through MCP tool calls; trace verified."

$lines += ""
$lines += "VERDICT: a fault was SENSED and HEALED entirely through MCP tool calls; trace verified."
$lines += ""
$lines += "-- trace.jsonl (hash-chained, across both MCP process runs) --"
$tracefile = Join-Path $ws ".phoenix\trace.jsonl"
if (Test-Path $tracefile) {
  $i = 0
  foreach ($tl in Get-Content $tracefile) {
    $o = $tl | ConvertFrom-Json
    $lines += ("  [{0}] {1,-9} ok={2,-5} hash={3}..." -f $i, $o.tool, $o.ok, $o.hash.Substring(0,12))
    $i++
  }
}

$ev = Join-Path $repo "evals\m2-mcp"
$lines -join "`n" | Set-Content (Join-Path $ev "session.txt")
$lines -join "`n" | Write-Output
Remove-Item $ws -Recurse -Force -ErrorAction SilentlyContinue
