---
type: Markdown Document
title: v0-spine-design.md
description: Code-graph knowledge extracted from `docs/v0-spine-design.md` (17 symbol(s), 0 cross-file edge(s)).
resource: docs/v0-spine-design.md
tags: [community-4, document]
timestamp: 2026-06-18T02:40:30Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `phoenix v0 spine — design (milestone m1)` | L1 | document |
| `v0-spine-design.md` | L1 | document |
| `open question for the human` | L100 | document |
| `transport` | L12 | document |
| `the v0 tools (contracts) — "four tools" honestly: sense, heal, snapshot, verify_trace` | L16 | document |
| `1. `sense` — objective failure detection (never self-grading)` | L18 | document |
| `code:block1 (sense(check: check) -> senseresult)` | L19 | document |
| `2. `heal` — one bounded, logged recovery (against an external recheck)` | L32 | document |
| `code:block2 (heal(strategy: strategy, ctx: healctx) -> healresult)` | L33 | document |
| `3. `snapshot` — blessed last-good state` | L48 | document |
| `code:block3 (snapshot(path, check: check) -> { snap_id, ts, blessed: bool)` | L49 | document |
| `4. `verify_trace` — tamper-evident (not tamper-proof) integrity` | L55 | document |
| `code:block4 (verify_trace() -> { ok: bool, rows, head_hash, broken_at? })` | L56 | document |
| `safety rails (v0, per design critique)` | L68 | document |
| `why an mcp server (not a cli, not a hook)` | L7 | document |
| `the v0 demo (what m1 must prove, with eval + screenshot)` | L76 | document |
| `why this is the right v0 (anti-astronomy)` | L95 | document |

# Citations

[1] Source file `docs/v0-spine-design.md` in repository `ATV-Phoenix`.
