---
type: Rust Source
title: sense.rs
description: Code-graph knowledge extracted from `src/sense.rs` (15 symbol(s), 0 cross-file edge(s)).
resource: src/sense.rs
tags: [community-0, community-6, code]
timestamp: 2026-06-18T02:40:30Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `sense.rs` | L1 | code |
| `hex()` | L106 | code |
| `sense()` | L114 | code |
| `de_string_or_vec()` | L12 | code |
| `sense_command()` | L122 | code |
| `sense_sha256()` | L156 | code |
| `sense_regex()` | L175 | code |
| `expect_accepts_int_or_string_or_null()` | L196 | code |
| `target_accepts_array_or_string()` | L213 | code |
| `de_string_or_number()` | L31 | code |
| `checkkind` | L54 | code |
| `check` | L64 | code |
| `senseresult` | L84 | code |
| `truncate()` | L90 | code |
| `sha256_file()` | L98 | code |

# In-file calls

6 intra-file call/method edge(s):

- `sha256_file()` calls `hex()` (L103)
- `sense()` calls `sense_command()` (L116)
- `sense()` calls `sense_sha256()` (L117)
- `sense()` calls `sense_regex()` (L118)
- `sense_command()` calls `truncate()` (L142)
- `sense_sha256()` calls `sha256_file()` (L158)

# Citations

[1] Source file `src/sense.rs` in repository `ATV-Phoenix`.
