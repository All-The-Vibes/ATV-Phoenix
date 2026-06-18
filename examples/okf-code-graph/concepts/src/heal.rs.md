---
type: Rust Source
title: heal.rs
description: Code-graph knowledge extracted from `src/heal.rs` (7 symbol(s), 3 cross-file edge(s)).
resource: src/heal.rs
tags: [community-0, code]
timestamp: 2026-06-18T01:47:16Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `heal.rs` | L1 | code |
| `strategy` | L14 | code |
| `healctx` | L20 | code |
| `healresult` | L36 | code |
| `heal()` | L44 | code |
| `heal_rollback()` | L51 | code |
| `heal_retry()` | L78 | code |

# Relationships

_Directed edges to concepts in other files. `candidate` marks INFERRED edges — name-matched, ~0.8 confidence; verify at the cited location before relying on them for a risky change._

- `heal_rollback()` **calls** [`sense()`](/concepts/src/sense.rs.md) (L53) — `candidate`
- `heal_retry()` **calls** [`sense()`](/concepts/src/sense.rs.md) (L81) — `candidate`
- `heal_rollback()` **calls** [`restore()`](/concepts/src/snapshot.rs.md) (L63) — `candidate`

# In-file calls

2 intra-file call/method edge(s):

- `heal()` calls `heal_rollback()` (L46)
- `heal()` calls `heal_retry()` (L47)

# Citations

[1] Source file `src/heal.rs` in repository `ATV-Phoenix`.
