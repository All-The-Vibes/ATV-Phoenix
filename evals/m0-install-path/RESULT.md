# Milestone M0 — Install-path & token/retrieval pillar validation

**Date:** 2026-06-09
**Goal:** Prove the exact distribution + retrieval mechanism Phoenix will use is real and works
**Verdict:** ✅ PASS — mechanism live on disk; graph built; structural query answered correctly from the graph

---

## What was validated (objective)

### 1. Prerequisites present
| Tool | Status | Version / Path |
|---|---|---|
| `uv` | ✅ | 0.9.24 — `~/.local/bin/uv.exe` |
| `graphify` | ✅ | pkg 0.8.13 (skill 0.4.1 — minor mismatch, noted) — `~/.local/bin/graphify.exe` |
| `copilot` CLI | ✅ | GitHub Copilot CLI 1.0.61 — `%APPDATA%/npm/copilot.cmd` (not on PATH; resolved) |
| `node` | ✅ | present (optional codegraph backend) |

### 2. TokenMasterX mechanism already installed (the Phoenix install pattern, live)
- Routing agent present: `~/.copilot/agents/token-master.agent.md`
  - declares `graphify-nav` **MCP server** (stdio, launched via `uv run`, `graphify_mcp.py`)
  - graph tools exposed: `find · callers · callees · impact · inheritors · explain`
  - reads graph from `.token-master/graph.json` (repo-relative)
- Plugin present: `~/.copilot/installed-plugins/_direct/token-master-plugin/` (plugin.json + skills)
- Also installed alongside: `anthropic-agent-skills` (document-skills, example-skills) — agentskills.io packs
- **This is exactly the Phoenix distribution model: plugin marketplace → routing agent (+ inline MCP) in user CLI home.**

### 3. Graph build (measured)
- Target: `ATV-Teams/packages/shared/src` (TypeScript)
- Command: `graphify update <src>`
- **Result: 1322 nodes, 1717 edges, 70 communities — built in 10.7s** (no LLM, no API key)
- Artifacts: `graph.json` (911 KB), `graph.html` (925 KB interactive viz), `GRAPH_REPORT.md` (19 KB)

### 4. Structural query answered FROM THE GRAPH (correctness vs ground truth)
- Query: `graphify explain "normalizeAgentUrlKey"` →
  - Reported: `<-- deriveAgentUrlKey() [calls]` at `agent-url-key.ts L10`
- Query: `graphify query "what calls deriveAgentUrlKey"` →
  - Reported edge: `deriveAgentUrlKey() --calls--> normalizeAgentUrlKey()`
- **Ground-truth check:** source `agent-url-key.ts:21` = `return normalizeAgentUrlKey(name) ?? ...`
  inside `deriveAgentUrlKey`. ✅ The graph's structural answer matches the actual code. No grep, no
  file-reading — answered from the prebuilt graph (the TokenMasterX value proposition, demonstrated).

---

## Screenshot evidence
![graph viz](screenshots/m0-graph-viz.png)
*1322-node interactive code graph (70 communities) rendered from `graph.html` — the structural index
Phoenix routes queries against instead of grep-re-reading files.*

---

## What worked
- Whole Phoenix install/retrieval mechanism is real and already on this machine — de-risks the platform.
- graphify builds a usable structural graph on a real TS codebase in ~11s, no LLM/API key needed.
- Structural query returned a **correct** caller edge verified against source — the core token-saving move works.

## What didn't / friction
- `copilot` not on the shell PATH (lives at `%APPDATA%/npm/`); resolved by absolute path. Note for install docs.
- graphify **skill 0.4.1 vs package 0.8.13** version mismatch warning (`graphify install` to update). Cosmetic now; fix before relying on skill-side behavior.
- kimi-webbridge daemon was down → used **headless Chrome (isolated clean profile)** for the screenshot. Worked first try.

## Implication for v0
- Token/retrieval pillar = **validated, adopt as-is.** v0 build scope narrows to the NOVEL spine only:
  the Rust MCP server exposing `sense` / `heal` / `trace`, proven by a fault detected+recovered in a live Copilot session.
