# Milestone M2 — the spine works over REAL MCP (GitHub Copilot's protocol)

**Date:** 2026-06-09
**Goal:** Make the proven M1 spine callable by GitHub Copilot — build the `rmcp` stdio MCP server and
prove a fault is sensed + healed THROUGH the protocol, not just as a library.
**Verdict:** ✅ PASS — `phoenix-mcp` speaks MCP 2025-06-18; a Copilot-like client drove the full
green→red→heal→green chain over stdio JSON-RPC in one session; `cargo test` 4/4.

---

## What was built
- `src/bin/phoenix_mcp.rs` — a real MCP server (`rmcp` 1.7) over **stdio**, exposing 4 tools:
  `phoenix_sense`, `phoenix_snapshot`, `phoenix_heal`, `phoenix_verify_trace` — thin adapters over the
  proven M1 spine lib. stdout is JSON-RPC only; diagnostics to stderr.
- `tests/m2_mcp_session.rs` — spawns the server, performs the MCP handshake, and drives the full
  self-heal flow over real JSON-RPC with the fault injected mid-session.

## Evals (objective)
**Protocol handshake + discovery (manual stdio probe):**
```
initialize -> protocolVersion 2025-06-18, tools capability, Phoenix instructions
tools/list -> phoenix_sense, phoenix_snapshot, phoenix_heal, phoenix_verify_trace
              (each with a full JSON Schema — Copilot knows exactly how to call them)
```
**Full self-heal over MCP, one continuous session (`cargo test --test m2_mcp_session`):**
```
[id2] phoenix_sense        baseline   -> ok=true      GREEN
[id3] phoenix_snapshot     bless      -> blessed=true snap_id=logic.txt.705be882...
       << inject fault: logic.txt -> answer=BROKEN >>
[id4] phoenix_sense        post-fault -> ok=false     RED (external command signal)
[id5] phoenix_heal         rollback   -> healed=true  (recheck via external command)
[id6] phoenix_sense        post-heal  -> ok=true      GREEN (recovered)
[id7] phoenix_verify_trace audit      -> ok=true rows>=5 (hash chain intact)
```
**Full suite: `cargo test` → 4 passed / 0 failed** (3 spine + 1 MCP-session).

## Screenshot evidence
![M2 over MCP](screenshots/m2-mcp-session.png)
*Copilot-like client driving sense→heal→verify through Phoenix's MCP tools over stdio JSON-RPC.*

## What worked
- `rmcp` 1.7 `#[tool_router]`/`#[tool]`/`#[tool_handler]` macros generated correct MCP tool schemas
  from the Rust types — Copilot gets fully-typed tool contracts for free.
- The handshake + `tools/call` worked over plain newline-delimited stdio; stdout stayed clean JSON-RPC.
- The proven M1 lib dropped straight in behind the MCP adapter — compose, don't rewrite.

## What didn't / friction (honest — integration testing earned its keep)
- **Real bug caught by end-to-end testing:** `heal(rollback)` resolved `ctx.path` against the process
  CWD instead of the workspace, so the first MCP run healed the wrong file (`healed=false`). Fixed by
  resolving `workspace.join(path)` (a no-op for absolute paths, so M1 tests still pass). This is exactly
  the class of bug a library-only test misses and a protocol test catches.
- First validation harness was PowerShell driving **two** server processes (to inject the fault between
  calls) — that fragmented the trace across processes and the string-parser misread fields. Replaced with
  a **single-process Rust integration test** (one stdio session, in-test asserts) — robust and committed.
- `ServerInfo` is `#[non_exhaustive]` → can't struct-literal it; build via `default()` + field assigns.

## Scope honesty
- Validated against a **Copilot-like MCP client** (the integration test), proving protocol-level
  correctness. Driving it from the *actual* `copilot` CLI binary in an interactive session is a thin
  remaining step (install the agent + `/mcp`), not a code risk — the protocol is proven here.
- Still "bounded objective recovery," not broad self-healing. Command timeout still not in-process enforced.

## Next (M3)
Package as an installable Copilot plugin (ATV-StarterKit-style: agent def + `mcp-servers` block +
`npx`/marketplace), and drive a real fault→heal from inside an interactive `copilot` session. Eval + screenshot.
