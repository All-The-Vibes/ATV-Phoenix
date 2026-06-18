---
type: Python Source
title: setup.py
description: Code-graph knowledge extracted from `.copilot-plugin/skills/phoenix-setup/setup.py` (13 symbol(s), 0 cross-file edge(s)).
resource: .copilot-plugin/skills/phoenix-setup/setup.py
tags: [community-8, code, rationale]
timestamp: 2026-06-18T02:40:30Z
okf_source: phoenix-code-graph
built_at_commit: d08041dc7fbd3f65b267c39d1a37e01af136f9f5
---

# Symbols

| Symbol | Location | Kind |
|--------|----------|------|
| `setup.py` | L1 | code |
| `check_companions()` | L119 | code |
| `install the bundled tokenmasterx; recommend the optional addy lifecycle pack.` | L120 | rationale |
| `install_skills()` | L128 | code |
| `copy phoenix's bundled skills into the copilot skills dir, then self-check them` | L129 | rationale |
| `main()` | L154 | code |
| `find_repo()` | L35 | code |
| `ensure_binary()` | L48 | code |
| `copilot_home()` | L63 | code |
| `register_mcp()` | L69 | code |
| `install_agent()` | L87 | code |
| `install_tokenmaster()` | L95 | code |
| `install the bundled tokenmasterx (vendor/token-master) for token-efficient code` | L96 | rationale |

# In-file calls

10 intra-file call/method edge(s):

- `check_companions()` calls `install_tokenmaster()` (L122)
- `install_skills()` calls `copilot_home()` (L134)
- `main()` calls `find_repo()` (L159)
- `main()` calls `ensure_binary()` (L161)
- `main()` calls `register_mcp()` (L162)
- `main()` calls `install_agent()` (L163)
- `main()` calls `install_skills()` (L164)
- `main()` calls `check_companions()` (L169)
- `register_mcp()` calls `copilot_home()` (L70)
- `install_agent()` calls `copilot_home()` (L88)

# Citations

[1] Source file `.copilot-plugin/skills/phoenix-setup/setup.py` in repository `ATV-Phoenix`.
