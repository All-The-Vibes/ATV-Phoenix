# Phoenix v0 spine — design (Milestone M1)

**Scope:** the ONE novel thing Phoenix adds that Copilot/TokenMasterX/skills don't have:
a fast Rust **MCP server** that lets GitHub Copilot **sense** objective failure and **heal** it,
with an append-only **trace**. Token/retrieval is already done (TokenMasterX, M0).

## Why an MCP server (not a CLI, not a hook)
Copilot connects to MCP servers via `/mcp` and calls their tools mid-session. That's the only
in-loop surface where Phoenix can (a) observe an objective signal and (b) act to recover, while
Copilot is doing the work. Validated install pattern (M0): routing agent + inline stdio MCP server.

## Transport
- **stdio JSON-RPC 2.0** (MCP standard), Rust crate **`rmcp`** (official Rust MCP SDK).
- Launched by Copilot from an agent's `mcp-servers:` block, exactly like TokenMasterX's `graphify-nav`.

## The v0 tools (contracts) — "four tools" honestly: sense, heal, snapshot, verify_trace

### 1. `sense` — objective failure detection (never self-grading)
```
sense(check: Check) -> SenseResult
Check  = { kind, target, expect? }
  kind ∈ { "command_exit" | "file_sha256" | "regex_in_file" }   // 3 kinds is enough for v0
    command_exit : run `target` (ARGV ONLY, no shell), pass iff exit == (expect ?? 0)
                   — bounded: timeout (default 60s), cwd within workspace, captured stdout/stderr
                     truncated to N KB, no shell interpolation
    file_sha256  : pass iff sha256(file `target`) == `expect`
    regex_in_file: pass iff regex `expect` matches contents of `target`
SenseResult = { ok: bool, evidence: string(truncated), signal: string, ts }
```
Rule: `sense` only reports objective signals. No LLM, no opinion. `ok=false` is honest, not a failure.

### 2. `heal` — one bounded, logged recovery (against an EXTERNAL recheck)
```
heal(strategy: Strategy, ctx: HealCtx) -> HealResult
Strategy ∈ { "retry" | "rollback" }
  retry    : re-run ctx.command (argv) up to ctx.max_attempts (hard cap 3); healed iff recheck passes
  rollback : restore ctx.path from the EXPLICIT ctx.snap_id (a blessed snapshot), atomic temp+rename
HealCtx = { command?, max_attempts?, path?, snap_id?, recheck: Check }
HealResult = { healed: bool, attempts, action: string, evidence: string, ts }
```
- **Bounded:** hard cap (≤3 retries; one rollback). No unbounded loops — answers the
  "agents stuck in loops burning tokens" pain.
- **Recheck is external:** `healed:true` only if `recheck` (a `sense` Check, ideally a test command)
  passes AFTER the action. Recovery is validated by an independent signal, not by the heal itself.
- **Safe restore:** atomic temp-file + rename; refuse if `ctx.path` escapes the workspace root or is a
  symlink; rollback uses an explicit `snap_id` so we never silently restore a bad/newer state.

### 3. `snapshot` — blessed last-good state
```
snapshot(path, check: Check) -> { snap_id, ts, blessed: bool }
  copies `path` to .phoenix/snapshots/<snap_id> ONLY IF `check` passes (blessed). Returns blessed:false
  (and no snap_id) if the check fails — we never snapshot a known-bad state as "good".
```

### 4. `verify_trace` — tamper-EVIDENT (not tamper-proof) integrity
```
verify_trace() -> { ok: bool, rows, head_hash, broken_at? }
trace is append-only JSONL at .phoenix/trace.jsonl; every tool call appends one event:
  { ts, tool, input_digest, ok|healed, evidence, signal, prev_hash, hash }
  hash = sha256(prev_hash + canonical_row_without_hash)   // same scheme as our proven scorecard
```
- **Honest claim:** hash-chaining makes the trace **tamper-evident** (re-derivation detects edits),
  NOT immutable — a local actor could rewrite the whole chain. `verify_trace` recomputes + reports the
  head hash; v0 echoes the head hash back to Copilot so the session has an external anchor.
- `tokens_in/out` deferred (an MCP server can't reliably see the host's token counts; revisit when
  Copilot exposes them). Token-per-outcome stays the goal, measured at the harness layer later.

## Safety rails (v0, per design critique)
- **stdout is JSON-RPC ONLY.** All logs/diagnostics go to stderr (tracing subscriber). A handshake test
  spawns the server and asserts a clean MCP init + tool call — accidental `println!` would corrupt the protocol.
- **Command execution:** argv-only (no shell), per-call timeout, cwd + path confined to configured
  workspace roots, output capture capped. No network/command allowlist bypass.
- **Pin versions:** pin `rmcp` + assert the MCP protocol version in a test; run a live compat check against
  Copilot's actual MCP launcher before claiming M1 done. Use only plain tools over stdio (no advanced MCP features).

## The v0 demo (what M1 must prove, with eval + screenshot)
**Behavioral, not tautological** (per design critique): the success criterion is an EXTERNAL invariant
(a test command's exit code), not "do the bytes equal the snapshot." Self-contained, deterministic,
no live model needed to prove the SPINE:
1. A tiny target project has a **passing test**. Run `sense({kind:"command_exit", target:["<test cmd>"]})`
   → `ok:true` (green baseline). `snapshot(src_file, check=<that passing check>)` captures last-good —
   **snapshot is only blessed if its check passed** (no blessing bad state).
2. **Inject a behavioral fault**: mutate `src_file` so the logic breaks (file still exists, different bytes).
3. `sense({kind:"command_exit", target:["<test cmd>"]})` → `ok:false` — failure detected via an
   *independent* signal (the test), not a self-made hash.
4. `heal({strategy:"rollback", snap_id, recheck:<the command_exit check>})` → restores the blessed
   snapshot via atomic temp-file+rename, then re-runs the test → `healed:true` only if the test passes again.
5. `verify_trace()` shows the full green→mutate→red→heal→green chain, hash-verified.
**Pass = an independently-observable failure (failing test) is detected AND passing behavior is
restored, proven by the trace.** Runs as a Rust integration test (`cargo test`) AND drivable live
from Copilot via `/mcp`.
> Framing discipline (per critique): this is **"bounded objective recovery,"** not broad "self-healing."
> Rollback is ONE strategy; we don't overclaim diagnosis/repair in v0.

## Why this is the right v0 (anti-astronomy)
- Smallest thing that proves the novel claim (sense+heal+trace), reuses our proven patterns
  (hash-chain trace, objective evidence), and needs no model to verify the spine works.
- Everything else (more check kinds, repair strategy, skill-graph heal, self-improvement) extends this.

## Open question for the human
- `heal` strategy set for v0: start with `retry` + `rollback` only? (repair/escalate later.) — default YES.
- Trace location: repo-local `.phoenix/trace.jsonl` (gitignored)? — default YES.
