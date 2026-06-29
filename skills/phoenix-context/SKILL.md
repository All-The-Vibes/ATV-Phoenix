---
type: Phoenix Skill
name: phoenix-context
description: Assemble the cheapest sufficient context for a task — route structural questions (who calls X, what breaks if I change Y, what inherits from Z) to the prebuilt code graph instead of grepping and re-reading files, and pull the relevant subgraph/snippet rather than whole directories. Use on any non-trivial codebase, before a change with unclear blast radius, or when the user says /phoenix-context or "what uses this".
license: MIT
---

# phoenix-context — make every token earn its place

## Overview
A model has no memory between turns, so the harness re-sends the whole transcript every turn — every
file you read is re-paid for on every subsequent turn. The cost that matters is not tokens *sent* but
tokens *processed, summed across all turns* until the task is done. `phoenix-context` collapses that:
structural questions go to a **prebuilt code graph** (the bundled TokenMasterX, `graphify`-backed),
answered in one bounded query, instead of grep-and-read loops that compound turn after turn.

> Pay once to understand structure, then never again.

## When to use
- Any non-trivial / unfamiliar codebase.
- Before a change whose blast radius is unclear ("what breaks if I change this signature?").
- During `phoenix-plan` (scope the real impact) and `phoenix-debug` (isolate the cause).
- Whenever you catch yourself opening a 3rd+ file to answer a structural question.

**When NOT to use:** a short, local question grep answers in ~one turn, or you already have the snippet.

## Two ways to assemble the same answer

```
   GREP its way there                    GRAPH lookup
turn 1  grep            2,000         turn 1  query graph   2,500
turn 2  read auth.py    6,000         turn 2  answer        3,000
turn 3  read server    11,000         ─────────────────────────
turn 4  read handlers  17,000         TOTAL PROCESSED       5,500
turn 5  grep narrower  19,000
turn 6  read config    24,000         Same answer.
turn 7  answer         26,000         19x less context processed.
─────────────────────────
TOTAL PROCESSED       105,000   ← it is the AREA UNDER THE CURVE, not the last turn
```

## Route structural questions to the graph
| Question | Graph query |
|---|---|
| "Who calls `X`?" / reverse dependencies | `callers` (or `impact` for the transitive blast radius) |
| "What does `X` call?" | `callees` |
| "What inherits / overrides `X`?" | `inheritors` |
| "Orient me on this unfamiliar symbol" | `explain` (or `find` to disambiguate a definition first) |
| "What breaks if I change `X`?" | `impact` |

The bundled TokenMasterX routing agent makes the graph the default for these. If `.token-master/graph.json`
is missing or stale (empty results for symbols you can clearly see), rebuild it with `/token-master`.

## Enforce, don't just offer
A graph the model never queries saves nothing. Left alone, models default to grep out of habit (in
TokenMaster's own runs: 0/15 unprompted, 8/8 when routed). So: **for any "who calls / what breaks"
question, reach for the graph first, on purpose.** That habit is where the token savings actually live.

## Honesty about the graph
`graphify` call edges are name-inferred candidates (~0.8 confidence), not a verified call graph. Treat
results as a **candidate list** and confirm a hit at its cited `file:line` before relying on it for a
risky change. For precision-critical impact analysis, escalate to the AST backend (`codegraph`). State
this uncertainty when it matters.

## Consuming OKF knowledge bundles
When the knowledge is shaped as an **OKF bundle** (a directory of markdown concepts — Phoenix's own
exported code graph, or any external catalog of runbooks / datasets / decisions), route to
`okf_ingest`, not grep. It is the same "pay once to orient" move: load the **index-first outline**
once, then open *exactly* the concept(s) you need.

```
python skills/phoenix-okf/scripts/okf_ingest.py <bundle>                 # outline (cheap, once)
python skills/phoenix-okf/scripts/okf_ingest.py <bundle> --query <type>  # locate, no file reads
python skills/phoenix-okf/scripts/okf_ingest.py <bundle> --full <path>   # open one concept
```

This is proven end-to-end on a real structural question in `evals/m5-okf-live/` (a live three-turn
disclosure answering "what cross-file edges does `src/heal.rs` have?"). As with the graph, the
outline is paid once and reused; whole-bundle dumps are the silent token killer. INFERRED edges in
an exported bundle are flagged `candidate` — same ~0.8-confidence honesty rule as above. See
`/phoenix-okf` to produce, validate, and sense bundles.

## Pull subgraphs, not directories
When you do need source, pull the **specific** functions/files the graph pointed to — not the whole
folder "for context". Whole-directory dumps are the silent token killer; the relevant subgraph is
almost always enough.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Grep is simpler, I'll just search." | Grep re-reads on every turn; the graph answers once. On multi-hop questions grep costs 3–8× more processed tokens. |
| "I'll read the whole module to be safe." | "To be safe" is how the context window fills with tokens you re-pay for every turn. Pull the subgraph. |
| "The graph might be stale, I'll grep instead." | If stale, rebuild it (`/token-master`) once. Falling back to grep abandons the savings on every future turn. |
| "Token cost doesn't matter, it's unlimited." | Even when $ is flat, tokens are a *latency* and *context-window* budget — fewer tokens = faster turns + more room for the actual task. |

## Red Flags
- Opening a 3rd file to answer "what uses this?". → One graph query.
- Reading a whole directory "for context". → Pull only the subgraph the graph identifies.
- Trusting an inferred edge for a risky refactor without checking the source. → Verify at `file:line`, or use the AST backend.
- Planning a change without querying its `impact`. → You're guessing the blast radius.

## Next
Feed the precise context into **`phoenix-plan`** (scoped steps), **`phoenix-build`** (surgical edits),
or **`phoenix-debug`** (isolated cause).
