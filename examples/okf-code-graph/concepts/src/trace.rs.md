---
type: Rust Source
title: trace.rs
description: Code-graph knowledge extracted from `src/trace.rs` (15 symbol(s), 0 cross-file edge(s)).
resource: src/trace.rs
tags: [community-5, code]
timestamp: 2026-06-18T01:47:16Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `trace.rs` | L1 | code |
| `.read_all()` | L106 | code |
| `.verify()` | L116 | code |
| `traceevent` | L12 | code |
| `digest_str()` | L129 | code |
| `ts()` | L135 | code |
| `trace` | L23 | code |
| `traceverify` | L28 | code |
| `now_ts()` | L35 | code |
| `hex()` | L43 | code |
| `row_hash()` | L52 | code |
| `.at()` | L65 | code |
| `.default_in()` | L69 | code |
| `.last_hash()` | L73 | code |
| `.append()` | L85 | code |

# In-file calls

14 intra-file call/method edge(s):

- `.append()` calls `row_hash()` (L100)
- `trace` method `.read_all()` (L106)
- `trace` method `.verify()` (L116)
- `.verify()` calls `.read_all()` (L117)
- `.verify()` calls `row_hash()` (L120)
- `digest_str()` calls `hex()` (L132)
- `ts()` calls `now_ts()` (L136)
- `row_hash()` calls `hex()` (L61)
- `trace` method `.at()` (L65)
- `trace` method `.default_in()` (L69)
- `trace` method `.last_hash()` (L73)
- `trace` method `.append()` (L85)
- `.append()` calls `.last_hash()` (L89)
- `.append()` calls `now_ts()` (L91)

# Citations

[1] Source file `src/trace.rs` in repository `ATV-Phoenix`.
