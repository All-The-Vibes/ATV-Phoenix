---
name: token-master
description: Turn on token-efficient code-graph routing for the current repository. Builds a structural code index and installs the routing agent so the host CLI answers "who calls X / what breaks if I change Y" from a prebuilt graph instead of repeated grep, cutting cumulative context tokens. Use when the user types /token-master or asks to enable token-efficient routing.
---

# /token-master

This skill turns on TokenMaster's token-efficient routing for the repository the user is working
in. It is the on-switch: it builds the code graph and installs the routing engine.

## What it does

1. Builds a structural **code graph** of the repo with `graphify` (no LLM, fast) — the default,
   cheapest backend.
2. Stores it at `.token-master/graph.json` and adds `.token-master/` to the repo's `.gitignore`.
3. Best-effort installs a second **`codegraph`** backend (AST-resolved call edges) for precision
   escalation, and indexes the repo with it. This needs `node` + `npm`; if they are missing the
   plugin still works graphify-only (the agent is written without the codegraph server).
4. Installs/refreshes the **`token-master` routing agent** (user scope) and its graph MCP servers.

The two backends are not interchangeable: graphify is the cheap default; codegraph is a targeted
escalation for precision-critical or sparse-call-graph cases (see "After setup"). If graphify's call
graph is **sparse** for the repo (common in JavaScript/TypeScript), setup prints a warning — that is
the signal codegraph will do the call-resolution work on that repo.

## How to run it

The setup script lives in this skill's own directory. Locate it reliably, then run it:

1. Run `/skills info token-master` and read the skill's directory path from the output.
2. Run the script, passing that directory and the repo root (normally the current working
   directory):

```
python "<skill-dir>/setup.py" "<repo-root>"
```

Then relay the script's summary output to the user verbatim.

- If the script reports that `graphify` (or `uv`) is not installed, tell the user to install the
  missing tool — `uv tool install graphify` (see https://github.com/safishamsi/graphify) or `uv`
  itself (https://docs.astral.sh/uv/) — then run `/token-master` again.
- The routing agent is loaded at CLI startup, so the user must **restart their CLI** before routing
  takes effect (unless it is already active). The setup script prints the exact host-specific
  restart command in its summary — relay that line as-is rather than guessing the host.

## After setup

Once the agent is active, the user just asks structural questions normally ("who calls X?", "what
breaks if I change Y?") and they are answered from the graph. To confirm it is working, ask a
known structural question and check that the answer comes from a `graphify-nav` MCP tool call.

The agent prefers `graphify-nav` (cheap) and escalates to `codegraph` (precise, ~2x tokens, AST-
resolved) only when it matters: graphify returned nothing for a symbol that exists, name collisions
where text matching over-reaches, or when exact `file:line` call sites are load-bearing. On a repo
where setup warned the call graph is sparse, expect that escalation to fire more often.

For **cross-session** continuity, the agent uses the host CLI's **native** session memory (no extra
server): keyword recall over past turns and the host's `--resume`/`--continue`. This is lexical and
opt-in, not automatic semantic memory — resume replays the full prior transcript (re-billed as
input), so it is only worth it after a large investigation, not for short sessions.

Re-run `/token-master` whenever the code has changed enough that the graph is stale.
