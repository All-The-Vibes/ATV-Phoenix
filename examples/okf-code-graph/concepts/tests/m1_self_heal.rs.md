---
type: Rust Source
title: m1_self_heal.rs
description: Code-graph knowledge extracted from `tests/m1_self_heal.rs` (5 symbol(s), 4 cross-file edge(s)).
resource: tests/m1_self_heal.rs
tags: [community-0, code]
timestamp: 2026-06-18T02:40:30Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `m1_self_heal.rs` | L1 | code |
| `check_contains()` | L15 | code |
| `green_red_heal_green_with_trace()` | L31 | code |
| `trace_is_tamper_evident()` | L80 | code |
| `snapshot_refuses_to_bless_bad_state()` | L99 | code |

# Relationships

_Directed edges to concepts in other files. `candidate` marks INFERRED edges — name-matched, ~0.8 confidence; verify at the cited location before relying on them for a risky change._

- `green_red_heal_green_with_trace()` **calls** [`heal()`](/concepts/src/heal.rs.md) (L64) — `candidate`
- `green_red_heal_green_with_trace()` **calls** [`sense()`](/concepts/src/sense.rs.md) (L40) — `candidate`
- `green_red_heal_green_with_trace()` **calls** [`snapshot()`](/concepts/src/snapshot.rs.md) (L45) — `candidate`
- `snapshot_refuses_to_bless_bad_state()` **calls** [`snapshot()`](/concepts/src/snapshot.rs.md) (L105) — `candidate`

# In-file calls

2 intra-file call/method edge(s):

- `snapshot_refuses_to_bless_bad_state()` calls `check_contains()` (L104)
- `green_red_heal_green_with_trace()` calls `check_contains()` (L39)

# Citations

[1] Source file `tests/m1_self_heal.rs` in repository `ATV-Phoenix`.
