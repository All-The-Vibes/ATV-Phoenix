---
type: Rust Source
title: demo_self_heal.rs
description: Code-graph knowledge extracted from `examples/demo_self_heal.rs` (3 symbol(s), 3 cross-file edge(s)).
resource: examples/demo_self_heal.rs
tags: [community-0, code]
timestamp: 2026-06-18T01:47:16Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `demo_self_heal.rs` | L1 | code |
| `main()` | L18 | code |
| `check_contains()` | L9 | code |

# Relationships

_Directed edges to concepts in other files. `candidate` marks INFERRED edges — name-matched, ~0.8 confidence; verify at the cited location before relying on them for a risky change._

- `main()` **calls** [`heal()`](/concepts/src/heal.rs.md) (L48) — `candidate`
- `main()` **calls** [`sense()`](/concepts/src/sense.rs.md) (L29) — `candidate`
- `main()` **calls** [`snapshot()`](/concepts/src/snapshot.rs.md) (L33) — `candidate`

# In-file calls

1 intra-file call/method edge(s):

- `main()` calls `check_contains()` (L28)

# Citations

[1] Source file `examples/demo_self_heal.rs` in repository `ATV-Phoenix`.
