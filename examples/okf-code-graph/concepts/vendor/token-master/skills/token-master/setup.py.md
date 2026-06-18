---
type: Python Source
title: setup.py
description: Code-graph knowledge extracted from `vendor/token-master/skills/token-master/setup.py` (25 symbol(s), 0 cross-file edge(s)).
resource: vendor/token-master/skills/token-master/setup.py
tags: [community-1, code, rationale]
timestamp: 2026-06-18T01:47:16Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `setup.py` | L1 | code |
| `_fail()` | L102 | code |
| `_ensure_gitignore_lines()` | L107 | code |
| `add any missing lines to .gitignore (best effort, idempotent).` | L108 | rationale |
| `_ensure_codegraph()` | L124 | code |
| `locate or install the codegraph shim.      returns (node_path, shim_path) if c` | L125 | rationale |
| `_codegraph_node_count()` | L205 | code |
| `return codegraph's indexed node count via ``status --json``, or none on failure.` | L206 | rationale |
| `_calls_edge_count()` | L229 | code |
| `return the count of 'calls' edges in a networkx node-link graph json.      the` | L230 | rationale |
| `_strip_codegraph_from_template()` | L248 | code |
| `remove the codegraph mcp-server block and tool reference from the agent template` | L249 | rationale |
| `_write_claude_mcp_servers()` | L302 | code |
| `merge tokenmaster's graph mcp server(s) into claude code's ``~/.claude.json``.` | L303 | rationale |
| `main()` | L342 | code |
| `_resolve_host()` | L44 | code |
| `pick the target host cli: 'claude' or 'copilot'.      priority: explicit --hos` | L45 | rationale |
| `_node_count()` | L589 | code |
| `_code_node_count()` | L597 | code |
| `_host_home()` | L62 | code |
| `user-scope home for the target host cli, honoring the host's env override.` | L63 | rationale |
| `_claude_mcp_config_path()` | L75 | code |
| `user-scope file where claude code stores its `mcpservers` map (`~/.claude.json`)` | L76 | rationale |
| `_git_root()` | L80 | code |
| `return the git toplevel for `start`, or `start` if not in a git repo.` | L81 | rationale |

# In-file calls

13 intra-file call/method edge(s):

- `_write_claude_mcp_servers()` calls `_claude_mcp_config_path()` (L310)
- `main()` calls `_resolve_host()` (L354)
- `main()` calls `_fail()` (L357)
- `main()` calls `_git_root()` (L358)
- `main()` calls `_code_node_count()` (L394)
- `main()` calls `_ensure_gitignore_lines()` (L409)
- `main()` calls `_host_home()` (L412)
- `main()` calls `_ensure_codegraph()` (L419)
- `main()` calls `_codegraph_node_count()` (L457)
- `main()` calls `_calls_edge_count()` (L475)
- `main()` calls `_strip_codegraph_from_template()` (L528)
- `main()` calls `_write_claude_mcp_servers()` (L544)
- `main()` calls `_node_count()` (L551)

# Citations

[1] Source file `vendor/token-master/skills/token-master/setup.py` in repository `ATV-Phoenix`.
