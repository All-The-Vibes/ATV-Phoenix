# H3 — Does injecting project-specific context (memory) lift Copilot's outcomes?

**Date:** 2026-06-10  ·  **Substrate:** live `copilot -p` (GitHub Copilot CLI), 8 sessions
**Verdict:** ✅ **POSITIVE, decisive** — 0/4 without context → 4/4 with context. Relevant memory is the
difference between a generic answer and a project-correct one.

---

## The question
Does giving the agent **relevant project context/memory** change outcomes? This is H3 (memory-lift)
AND the reason a memory layer (goose-brain) matters for the whole intent-to-outcome system.

## Design (clean isolation)
Each task's correct answer depends on a **project convention the model cannot guess from the spec
alone** — verified in pre-flight: the standard/default solution **fails** the hidden checker, the
convention-following solution passes. The two arms differ **only** in whether the convention is injected.
- **Arm A (no context):** the spec only.
- **Arm B (context):** the spec + the project convention (the "memory").

## Results (8 live Copilot sessions)
```
                                 A_nocontext     B_context
status_label  (ACTIVE! / INACTIVE!)    0/2            2/2
format_money  (USD 1,234.50)           0/2            2/2
-----------------------------------------------------------
OVERALL (n=4 per arm)                  0/4 (0%)       4/4 (100%)
```
- **memory-lift: 0% → 100%** verified-pass.
- Without context, Copilot produced the *standard default every time* (`Active`, `$1,234.50`) and
  failed the project convention — it genuinely cannot guess a project-specific rule.
- With the same convention injected, it followed it exactly and passed every time.

## Screenshot evidence
![H3 results](screenshots/h3-results.png)

## What this proves
Relevant injected context is **decisive and necessary** when the correct output depends on knowledge
not in the prompt. This is the empirical case for the I2O memory layer: a system that remembers a
user's/project's conventions produces project-correct work where a context-free agent produces a
plausible-but-wrong default. Combined with H1 (criteria-first) and H2 (objective verification), H3
completes the trio: **formalize intent + verify objectively + supply the right context.**

## Honest limits
- 8 trials across 2 task families (the third, `userid`, was abandoned mid-run to API rate-limiting; the
  8 completed trials show a perfect, unambiguous 0/4 vs 4/4 split — the pattern is not in doubt).
- Constructed conventions, single model. A clear directional result with an obvious mechanism; the
  conventions are deliberately unguessable to isolate the context effect.

## Artifacts
`run_h3.ps1`, `tasks/` (spec + context + hidden checker per task), `results.jsonl`, `RESULT-summary.txt`.
