# H2 — Does an objective verifier (Phoenix) change real Copilot outcomes?

**Date:** 2026-06-09  ·  **Substrate:** live `copilot -p` (GitHub Copilot CLI v1.0.61), 20 sessions
**Verdict:** ✅ **POSITIVE where it matters** — Phoenix eliminated a 40% silent-failure rate to 0%,
with zero regressions. The whole gain is on tasks where the agent can't anticipate the acceptance
criteria (the real-world case).

---

## The question (H2, reframed onto the real runtime)
Vanilla agents self-judge: they implement, declare "done," and ship — even when the result is
silently broken. Does giving the agent an **objective verifier** (`phoenix_sense` + `phoenix_heal`)
change that? This is H2 ("a separate verifier catches silent failures a single pass misses") AND
Phoenix's core product claim, tested on the actual runtime instead of toy tasks.

## Design (clean control)
Same task, same model; **scored externally by a hidden acceptance checker (ground truth)**.
- **Arm A (vanilla):** implement from the spec, self-judge, end with DONE. No checker visible, no Phoenix.
- **Arm B (phoenix):** implement, then `phoenix_sense` the checker and fix until green, end with DONE.
- Two task families × reps: **well-specified** (slugify, format_duration, to_roman) and
  **underspecified** (clamp, initials — the spec omits an acceptance criterion the checker enforces).
- Pre-flight: every checker verified to accept a correct solution and reject a naive one (no LLM).

## Results (20 live Copilot sessions)
```
                       A_vanilla                    B_phoenix
                 pass  silent-fail  phoenix    pass  silent-fail  phoenix
WELL-SPECIFIED    6/6      0          0/6       6/6      0          6/6    (ceiling: both perfect)
UNDERSPECIFIED    0/4      4          0/4       4/4      0          4/4    <== the signal
-----------------------------------------------------------------------------------
OVERALL (n=10)    6/10     4 (40%)    0/10      10/10    0 (0%)     10/10
```
- **silent-failure rate** (claimed DONE but checker fails): **40% → 0%**
- **verified-pass rate**: **60% → 100%**
- **regressions**: **0** (Phoenix never broke a task vanilla got right)
- **tool usage**: Phoenix called in **10/10** Phoenix runs, **0/10** vanilla runs

## Screenshot evidence
![H2 results](screenshots/h2-results.png)

## What this proves (and doesn't)
- **PROVES:** when acceptance criteria exceed what the agent can infer from the prompt, vanilla Copilot
  ships broken code with false confidence — *every time* in this run — and Phoenix's objective
  verify+heal loop catches and fixes it *every time*. That is the product's reason to exist, live.
- **The ceiling, honestly:** on well-specified tasks the strong model already passes, so Phoenix changes
  nothing (6/6 = 6/6). Same lesson as the H1 arc — verification's value concentrates where failure is
  possible. We report both halves; a tool that "wins everywhere" would be measuring an artifact.
- **Enforce vs offer** (TokenMasterX's lesson, replicated): an unprompted agent self-verified 0/10 times.
  The value isn't *offering* a verifier — it's the harness *enforcing* the verify+heal loop.

## Honest limits
- 2 reps/task, single model (Copilot default), deterministic checkers. A clear directional signal with an
  unambiguous mechanism — worth replicating at larger n before a hard statistical claim.
- "Underspecified" tasks deliberately hide a criterion. That models the real case (downstream tests the
  agent can't see) but is a constructed scenario; not every real failure is this clean.

## Why it matters for the product (M4)
This is the headline number a shippable Phoenix needs, the way TokenMasterX leads with "−73% tokens":
**"Phoenix cut Copilot's silent-failure rate from 40% to 0% on tasks with hidden acceptance criteria,
with zero regressions."** H2 (a foundational I2O hypothesis) and Phoenix's product proof, in one run.

## Artifacts
`run_h2.ps1` + `run_h2_adv.ps1` (runners), `tasks/` (specs + hidden checkers), `results.jsonl` +
`results_adv.jsonl` + `results_all.jsonl` (raw per-trial data), `RESULT-summary.txt`.
