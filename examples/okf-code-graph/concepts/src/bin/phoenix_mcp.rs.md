---
type: Rust Source
title: phoenix_mcp.rs
description: Code-graph knowledge extracted from `src/bin/phoenix_mcp.rs` (16 symbol(s), 6 cross-file edge(s)).
resource: src/bin/phoenix_mcp.rs
tags: [community-0, code]
timestamp: 2026-06-18T02:40:30Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `phoenix_mcp.rs` | L1 | code |
| `.phoenix_verify_trace()` | L107 | code |
| `.get_info()` | L115 | code |
| `main()` | L129 | code |
| `run_cli()` | L146 | code |
| `workspace()` | L25 | code |
| `trace()` | L31 | code |
| `jdigest()` | L35 | code |
| `senseargs` | L42 | code |
| `snapshotargs` | L48 | code |
| `healargs` | L56 | code |
| `phoenix` | L64 | code |
| `.new()` | L70 | code |
| `.phoenix_sense()` | L76 | code |
| `.phoenix_snapshot()` | L84 | code |
| `.phoenix_heal()` | L98 | code |

# Relationships

_Directed edges to concepts in other files. `candidate` marks INFERRED edges — name-matched, ~0.8 confidence; verify at the cited location before relying on them for a risky change._

- `.phoenix_heal()` **calls** [`heal()`](/concepts/src/heal.rs.md) (L100) — `candidate`
- `run_cli()` **calls** [`heal()`](/concepts/src/heal.rs.md) (L168) — `candidate`
- `.phoenix_sense()` **calls** [`sense()`](/concepts/src/sense.rs.md) (L77) — `candidate`
- `run_cli()` **calls** [`sense()`](/concepts/src/sense.rs.md) (L152) — `candidate`
- `.phoenix_snapshot()` **calls** [`snapshot()`](/concepts/src/snapshot.rs.md) (L87) — `candidate`
- `run_cli()` **calls** [`snapshot()`](/concepts/src/snapshot.rs.md) (L160) — `candidate`

# In-file calls

21 intra-file call/method edge(s):

- `.phoenix_heal()` calls `trace()` (L101)
- `.phoenix_heal()` calls `jdigest()` (L101)
- `phoenix` method `.phoenix_verify_trace()` (L107)
- `.phoenix_verify_trace()` calls `trace()` (L108)
- `phoenix` method `.get_info()` (L115)
- `main()` calls `run_cli()` (L138)
- `main()` calls `.new()` (L141)
- `run_cli()` calls `workspace()` (L147)
- `run_cli()` calls `trace()` (L153)
- `run_cli()` calls `jdigest()` (L153)
- `trace()` calls `workspace()` (L32)
- `phoenix` method `.new()` (L70)
- `phoenix` method `.phoenix_sense()` (L76)
- `.phoenix_sense()` calls `trace()` (L78)
- `.phoenix_sense()` calls `jdigest()` (L78)
- `phoenix` method `.phoenix_snapshot()` (L84)
- `.phoenix_snapshot()` calls `workspace()` (L85)
- `.phoenix_snapshot()` calls `trace()` (L89)
- `.phoenix_snapshot()` calls `jdigest()` (L89)
- `phoenix` method `.phoenix_heal()` (L98)
- `.phoenix_heal()` calls `workspace()` (L99)

# Citations

[1] Source file `src/bin/phoenix_mcp.rs` in repository `ATV-Phoenix`.
