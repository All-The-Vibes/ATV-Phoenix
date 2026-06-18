---
type: Reference
title: phoenix-okf sense recipes
description: Ready-to-run command_exit sense checks (OKF conformance + freshness) for the Phoenix spine.
tags: [okf, sense, reference]
---

# phoenix-okf sense recipes

Ready-to-run objective checks for the Phoenix spine. Each file is a `command_exit` check the
`phoenix_sense` / `phoenix_accept` tools (or the `phoenix-mcp` CLI) consume directly.

| Recipe | Senses | Green when |
|---|---|---|
| `okf-conformant.json` | OKF v0.1 conformance of `examples/okf-code-graph/` | `okf_validate.py` exits 0 |
| `okf-fresh.json` | bundle is in sync with `.token-master/graph.json` | `okf_freshness.py` exits 0 |

Run from the repo root (paths are repo-relative):

```
target/release/phoenix-mcp.exe sense  @skills/phoenix-okf/checks/okf-conformant.json
target/release/phoenix-mcp.exe sense  @skills/phoenix-okf/checks/okf-fresh.json
target/release/phoenix-mcp.exe accept @skills/phoenix-okf/checks/okf-conformant.json
```

`sense` returns `{ok, signal, evidence}` and exits 0/1. `accept` returns `ok=true` only if the
tamper-evident trace proves this exact check went red→green and is green now — the objective stop
signal for an autonomous loop. To point a recipe at a different bundle, edit the last `target`
argument.
