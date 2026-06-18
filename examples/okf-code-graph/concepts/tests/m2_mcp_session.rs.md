---
type: Rust Source
title: m2_mcp_session.rs
description: Code-graph knowledge extracted from `tests/m2_mcp_session.rs` (8 symbol(s), 0 cross-file edge(s)).
resource: tests/m2_mcp_session.rs
tags: [community-18, code]
timestamp: 2026-06-18T01:47:16Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `m2_mcp_session.rs` | L1 | code |
| `.start()` | L15 | code |
| `.send()` | L29 | code |
| `.read_id()` | L36 | code |
| `.drop()` | L52 | code |
| `tool_json()` | L59 | code |
| `copilot_drives_sense_and_heal_over_mcp()` | L65 | code |
| `server` | L8 | code |

# In-file calls

8 intra-file call/method edge(s):

- `server` method `.start()` (L15)
- `server` method `.send()` (L29)
- `server` method `.read_id()` (L36)
- `server` method `.drop()` (L52)
- `copilot_drives_sense_and_heal_over_mcp()` calls `.start()` (L78)
- `copilot_drives_sense_and_heal_over_mcp()` calls `.send()` (L79)
- `copilot_drives_sense_and_heal_over_mcp()` calls `.read_id()` (L80)
- `copilot_drives_sense_and_heal_over_mcp()` calls `tool_json()` (L85)

# Citations

[1] Source file `tests/m2_mcp_session.rs` in repository `ATV-Phoenix`.
