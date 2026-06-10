# Milestone M3 — Phoenix heals a fault INSIDE the live GitHub Copilot CLI

**Date:** 2026-06-09
**Goal:** Install Phoenix into GitHub Copilot and prove Copilot itself calls the tools to sense + heal
a real fault — not a test harness, the actual `copilot` CLI.
**Verdict:** ✅ PASS — in a real `copilot -p` session, Copilot autonomously sensed an objective failure,
healed it (rollback), confirmed recovery, and the file was fixed on disk, with a verified trace.

---

## How Phoenix is installed (the distribution mechanism)
- `dist/phoenix.agent.md` — a Copilot agent definition mirroring TokenMasterX's pattern (frontmatter
  with `tools` + inline `mcp-servers` stdio block).
- `dist/install.ps1` — ATV-StarterKit-style installer: builds the release binary, stamps its path into
  the agent file, installs to `~/.copilot/agents/`.
- **What actually worked for live invocation:** registering the MCP server in `~/.copilot/mcp-config.json`
  (the user MCP registry where `memory`/`azure`/etc. live). Copilot auto-discovered the `phoenix` tools.

## The live proof (`copilot -p`, GitHub Copilot CLI v1.0.61)
Prompt: *"use the phoenix MCP tools to verify + recover logic.txt (healthy iff it contains GOOD_MARKER)."*
Copilot's actual tool calls:
```
phoenix_sense  -> {"ok":false}   RED  (failure detected via an external findstr command)
phoenix_heal   -> {"healed":true,"attempts":1,"action":"rollback logic.txt <- snapshot ..."}
phoenix_sense  -> {"ok":true}    GREEN (recovered, confirmed by the external recheck)
Copilot reported: "Before: false / After: true"
File on disk:     answer=GOOD_MARKER   (actually fixed)
Cost:             ~14.9 AI credits, 187.6k tokens, 36s
```
The tamper-evident trace Phoenix wrote **during the live Copilot session** (`evals/m3-live-copilot/live-trace.jsonl`):
```
[0] sense ok=false  hash=0f2254c6...  prev=GENESIS
[1] heal  ok=true   hash=a67e1126...  prev=0f2254c6...
[2] sense ok=true   hash=6ec26de8...  prev=a67e1126...
```

## Screenshot evidence
![M3 live Copilot](screenshots/m3-live-copilot.png)

## What worked
- **Phoenix gave Copilot the missing organ — and Copilot used it.** Sense→heal→verify, in a real
  session, file fixed on disk, no harness — just the prompt and the MCP tools.
- MCP-config registration is a clean one-file install; `rmcp` schemas told Copilot exactly how to call.
- The proven spine (M1) + MCP server (M2) dropped straight in. Compose-not-rewrite held all the way up.

## What didn't / friction — and the bug live testing caught
- **Real bug, caught only by the live LLM:** Copilot naturally passes `expect: 0` as an INTEGER; the
  schema wanted a string → first `phoenix_sense` call failed `-32602 invalid type: integer`. Copilot
  self-corrected and continued, but it wasted a turn. **Fixed:** `expect` now accepts string OR number
  OR null via a custom deserializer (`de_string_or_number`) + a unit test. **Re-verified live:** Copilot
  passed `expect:0` as an integer and the call succeeded cleanly ("did not error"). This is exactly the
  class of bug no library/protocol test surfaces — only a real model calling the tool does.
- Loose `~/.copilot/agents/phoenix.agent.md` was NOT picked up by `--agent phoenix` (Copilot resolves
  `--agent` against registered/installed-plugin agents; token-master is in `config.json`). Used the
  MCP-config registry instead for the live proof. Proper marketplace/`npx` plugin registration (so
  `--agent phoenix` works) is the remaining packaging step — a distribution detail, not a capability gap.
- Driving `copilot -p` headlessly is slow (30s–min+ per run) and an inline `--additional-mcp-config`
  JSON arg gets mangled by the PowerShell→cmd shim; the config-file path is the reliable mechanism.

## Scope honesty
- This is the real thing: an actual Copilot session healing a real fault. Still "bounded objective
  recovery," and still on a deterministic scenario (one file, one invariant, a pre-seeded snapshot).
  The next frontier is messy, multi-file, fuzzy-success real work — and Copilot *choosing* to snapshot
  before risky edits unprompted.

## Tests
`cargo test` → 5 passed / 0 failed (expect-flex unit + 3 spine + 1 MCP-session). Zero regressions.

## Next (M4+)
- Proper plugin packaging so `copilot --agent phoenix` works (marketplace/npx), making install one command.
- A harder live scenario: Copilot edits real code, breaks a real test, and self-heals — measured.
