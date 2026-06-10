# Milestone M1 — the self-healing spine (sense / heal / snapshot / trace)

**Date:** 2026-06-09
**Goal:** Build the ONE novel thing Phoenix adds — a Rust spine that SENSES objective failure and HEALS
it (bounded, reversible, logged), proven by a NON-tautological behavioral demo.
**Verdict:** ✅ PASS — `cargo test` green (3/3); behavioral green→red→heal→green proven against an
external signal; trace hash-verified.

---

## What was built (Rust lib `phoenix`)
| Module | Role |
|---|---|
| `sense` | objective checks: `command_exit` (argv, no shell), `file_sha256`, `regex_in_file`. No LLM. |
| `snapshot` | captures last-good state **only if a check passes** (never blesses a bad state); explicit `snap_id`. |
| `heal` | bounded recovery: `rollback` (atomic temp+rename to a blessed snapshot) / `retry` (≤3). `healed=true` only if an **external recheck** passes. |
| `trace` | append-only JSONL, **hash-chained** (sha256(prev_hash+canonical_row)); `verify()` is tamper-EVIDENT. |
| `phoenix-mcp` (bin) | MCP server entrypoint (stub; rmcp/stdio wiring is the next milestone). |

## The demo is NOT tautological (design-critique fix)
A rubber-duck critique flagged the original demo (corrupt a file, restore it, check bytes==snapshot) as
**circular** — it only proves "restore restores." Fix adopted: the success criterion is an **external
invariant** — a real command's exit code (`findstr`/`grep` on a sentinel), NOT the snapshot bytes.

## Evals (objective)
```
cargo test  ->  3 passed; 0 failed
  green_red_heal_green_with_trace   ok   (behavioral: external signal green->red->green)
  trace_is_tamper_evident           ok   (edit row 0 -> verify() catches it, broken_at=0)
  snapshot_refuses_to_bless_bad_state ok (won't snapshot a failing state)
```
Runnable demo (`cargo run --example demo_self_heal`) emits a verified 4-row trace:
```
1. GREEN baseline   -> sense.ok = true
2. BLESS snapshot   -> logic.txt.<hash> (blessed=true)
3. INJECT fault     -> sense.ok = false   (RED via external command exit code)
4. HEAL rollback    -> healed = true (attempts=1, recheck via external command)
5. TRACE verify     -> ok=true rows=4
   [0] sense    ok=true   [1] snapshot ok=true   [2] sense ok=false   [3] heal ok=true
```

## Screenshot evidence
![M1 self-heal](screenshots/m1-self-heal.png)
*Full green→red→heal→green chain with a hash-verified trace — recovery proven by an independent signal.*

## What worked
- Pure-Rust testable spine compiles and passes first run after fixes; demo is deterministic, no model needed.
- Hash-chained trace reuses our proven scorecard scheme; `verify()` catches tampering at the exact row.
- The critique-driven pivot to an **external** success signal makes the self-heal claim credible, not circular.

## What didn't / friction (honest)
- First design (file-hash rollback demo) was **tautological** — caught by rubber-duck BEFORE coding. Pivoted to a command-exit invariant.
- `command_exit` timeout is documented but not yet enforced in-process (v0 limitation; caller/test bounds it). To harden before live Copilot use.
- MCP/stdio (`rmcp`) wiring intentionally deferred — the spine is proven independently of protocol churn. That live `/mcp` integration is the next milestone (M2).

## Scope honesty
- Framed as **"bounded objective recovery,"** not broad "self-healing." Rollback is one strategy; no diagnosis/repair claimed in v0.
- `tokens_in/out` deferred (an MCP server can't see host token counts reliably yet).

## Next (M2)
Wire the spine into a live GitHub Copilot session via `rmcp` stdio MCP server + `/mcp`; prove a fault is
sensed+healed *from inside Copilot* (not just `cargo test`). Eval + screenshot of the live session.
