---
type: Rust Source
title: snapshot.rs
description: Code-graph knowledge extracted from `src/snapshot.rs` (5 symbol(s), 1 cross-file edge(s)).
resource: src/snapshot.rs
tags: [community-0, code]
timestamp: 2026-06-18T01:47:16Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `snapshot.rs` | L1 | code |
| `snap_dir()` | L14 | code |
| `snapshot()` | L20 | code |
| `restore()` | L35 | code |
| `snapshotresult` | L8 | code |

# Relationships

_Directed edges to concepts in other files. `candidate` marks INFERRED edges — name-matched, ~0.8 confidence; verify at the cited location before relying on them for a risky change._

- `snapshot()` **calls** [`sense()`](/concepts/src/sense.rs.md) (L21) — `candidate`

# In-file calls

2 intra-file call/method edge(s):

- `snapshot()` calls `snap_dir()` (L25)
- `restore()` calls `snap_dir()` (L36)

# Citations

[1] Source file `src/snapshot.rs` in repository `ATV-Phoenix`.
