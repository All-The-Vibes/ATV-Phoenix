---
type: Python Source
title: graphify_mcp.py
description: Code-graph knowledge extracted from `vendor/token-master/skills/token-master/graphify_mcp.py` (22 symbol(s), 0 cross-file edge(s)).
resource: vendor/token-master/skills/token-master/graphify_mcp.py
tags: [community-2, code, rationale]
timestamp: 2026-06-18T01:47:16Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `graphify_mcp.py` | L1 | code |
| `_ambiguity_msg()` | L117 | code |
| `_resolve()` | L126 | code |
| `_loc()` | L132 | code |
| `find()` | L140 | code |
| `resolve a symbol name to its definition(s) in the code graph.      returns eac` | L141 | rationale |
| `callers()` | L162 | code |
| `list direct callers of a function/method (one hop, reverse `calls`).      each` | L163 | rationale |
| `callees()` | L201 | code |
| `list what a function/method directly calls (one hop, forward `calls`).` | L202 | rationale |
| `impact()` | L236 | code |
| `transitive blast radius: every function/method that can reach `symbol`     thro` | L237 | rationale |
| `inheritors()` | L285 | code |
| `list classes that inherit from `symbol` (reverse `inherits` edges) and,     for` | L286 | rationale |
| `explain()` | L320 | code |
| `show a symbol's node plus all its immediate neighbors across every relation` | L321 | rationale |
| `_find_graph()` | L47 | code |
| `resolve the graph file. absolute graph_path is used as-is; a relative one     i` | L48 | rationale |
| `_norm()` | L61 | code |
| `_log()` | L65 | code |
| `_ensure_loaded()` | L76 | code |
| `load the graph on first use. returns an error message string on failure,     or` | L77 | rationale |

# In-file calls

31 intra-file call/method edge(s):

- `_ensure_loaded()` calls `_norm()` (L107)
- `_ambiguity_msg()` calls `_loc()` (L118)
- `_resolve()` calls `_norm()` (L129)
- `find()` calls `_ensure_loaded()` (L145)
- `find()` calls `_log()` (L148)
- `find()` calls `_resolve()` (L149)
- `find()` calls `_loc()` (L155)
- `callers()` calls `_ensure_loaded()` (L167)
- `callers()` calls `_log()` (L170)
- `callers()` calls `_resolve()` (L171)
- `callers()` calls `_ambiguity_msg()` (L175)
- `callees()` calls `_ensure_loaded()` (L203)
- `callees()` calls `_log()` (L206)
- `callees()` calls `_resolve()` (L207)
- `callees()` calls `_ambiguity_msg()` (L211)
- `callees()` calls `_loc()` (L223)
- `impact()` calls `_ensure_loaded()` (L241)
- `impact()` calls `_log()` (L244)
- `impact()` calls `_resolve()` (L245)
- `impact()` calls `_ambiguity_msg()` (L249)
- `impact()` calls `_loc()` (L277)
- `inheritors()` calls `_ensure_loaded()` (L288)
- `inheritors()` calls `_log()` (L291)
- `inheritors()` calls `_resolve()` (L292)
- `inheritors()` calls `_ambiguity_msg()` (L296)
- `inheritors()` calls `_loc()` (L309)
- `explain()` calls `_ensure_loaded()` (L324)
- `explain()` calls `_log()` (L327)
- `explain()` calls `_resolve()` (L328)
- `explain()` calls `_loc()` (L334)
- `_ensure_loaded()` calls `_find_graph()` (L82)

# Citations

[1] Source file `vendor/token-master/skills/token-master/graphify_mcp.py` in repository `ATV-Phoenix`.
