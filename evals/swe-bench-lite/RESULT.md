# SWE-bench-style Lite Benchmark — ATV-Phoenix

A small, honest, **SWE-bench-style** evaluation of whether Phoenix's enforced
objective gate changes the *resolved rate* on real bug-fix tasks.

> **Scope honesty.** This is a **SWE-bench-*style*** harness, **not** the official
> SWE-bench dataset. It borrows SWE-bench's *evaluation contract* (the part that makes
> the metric trustworthy) but uses small self-contained Python tasks instead of real
> GitHub repos. The official benchmark needs Docker + per-repo checkouts, which is
> heavy/unreliable on Windows. n is small (9 tasks, 1 rep, 1 model) — read the results
> as **directional**, not as a leaderboard number.

## The contract (this is what makes it legit)

Straight from SWE-bench: a task is **RESOLVED** iff, after the agent's edit,

- **every** `FAIL_TO_PASS` test passes (the bug is actually fixed), **AND**
- **every** `PASS_TO_PASS` test still passes (no regression introduced).

Each task ships:

| file | role |
|------|------|
| `solution.py` | the code under test, in its **buggy** state |
| `problem.md`  | the issue the agent sees (no tests) |
| `test_f2p.py` | `FAIL_TO_PASS` — red while buggy, must go green |
| `test_p2p.py` | `PASS_TO_PASS` — green while buggy, must stay green |

Every task was validated before the run: **F2P red + P2P green in the buggy state**
(a real failing bug) and **solvable** (a reference fix turns F2P green while keeping
P2P green). No rigged or impossible tasks.

## Two arms

| arm | what it gets | how it judges "done" |
|-----|--------------|----------------------|
| **A — vanilla** | `solution.py` + `problem.md` only (**tests hidden**) | self-judges; ends when it *thinks* it's right |
| **B — phoenix** | same, **plus the tests as an objective gate** | must `phoenix_sense` pytest **green**, heal on red, `verify_trace`, then DONE |

**Confound, stated plainly:** arm B sees the tests, arm A does not. That asymmetry
*is the intervention* — Phoenix's whole job is to **supply and enforce an objective
gate**. So this measures "resolved-rate without vs with Phoenix's enforced gate,"
which is exactly the product claim. Scoring is identical and blind for both arms (the
same hidden F2P/P2P contract, applied after the agent finishes).

## Tasks

**Tier 1 — well-specified (5).** The issue spells out the fix, *including the edge
cases* (e.g. `round(2.675,2)` → `2.68`): `cache-lru`, `csv-parser`, `date-range`,
`money-round`, `retry-backoff`.

**Tier 2 — underspecified (4).** Terse GitHub-issue-style reports that state **only
the reporter's symptom**; the F2P tests cover reasonable edges the issue never
mentions: `hard-slugify`, `hard-titlecase`, `hard-truncate`, `hard-dedupe`.

## Results

Model: GitHub Copilot CLI 1.0.61. 9 tasks × 2 arms × 1 rep = 18 agent runs.

| tier | A — vanilla | B — phoenix |
|------|:-----------:|:-----------:|
| Tier 1 — well-specified (n=5) | **5/5 (100%)** | **5/5 (100%)** |
| Tier 2 — underspecified (n=4) | **2/4 (50%)** | **4/4 (100%)** |
| **Overall (n=9)** | **7/9 (78%)** | **9/9 (100%)** |

Regressions introduced (P2P broken): **0** in either arm.

### Per-task

| task | tier | A f2p / p2p / resolved | B f2p / p2p / resolved |
|------|------|:--:|:--:|
| cache-lru      | 1 | 1 / 1 / ✅ | 1 / 1 / ✅ |
| csv-parser     | 1 | 1 / 1 / ✅ | 1 / 1 / ✅ |
| date-range     | 1 | 1 / 1 / ✅ | 1 / 1 / ✅ |
| money-round    | 1 | 1 / 1 / ✅ | 1 / 1 / ✅ |
| retry-backoff  | 1 | 1 / 1 / ✅ | 1 / 1 / ✅ |
| hard-dedupe    | 2 | 1 / 1 / ✅ | 1 / 1 / ✅ |
| hard-truncate  | 2 | 1 / 1 / ✅ | 1 / 1 / ✅ |
| **hard-slugify**   | 2 | **0 / 1 / ❌** | 1 / 1 / ✅ |
| **hard-titlecase** | 2 | **0 / 1 / ❌** | 1 / 1 / ✅ |

## What this shows (and doesn't)

1. **On well-specified tasks: ceiling.** Modern Copilot resolves clear, fully-specified
   bugs single-pass. Phoenix adds **no resolved-rate lift here — and does no harm**
   (still 100%, 0 regressions). Honest null, same regime the I2O H1 nulls located.

2. **On underspecified tasks: Phoenix lifts resolved-rate 50% → 100%.** Two of four
   flipped from unresolved to resolved.

3. **Both vanilla misses are *silent failures*, not crashes.** In `hard-slugify` and
   `hard-titlecase`, vanilla's fix kept **P2P green** (the happy path worked) but failed
   **F2P** (the hidden edges) — `f2p=0, p2p=1`. The fix *looked* done and passed the
   obvious case; it was quietly **incomplete**. That is precisely the failure mode the
   I2O H2 experiment measured, now reproduced under a SWE-bench contract: **an enforced
   objective gate converts "looks done" into "is done."**

### Limits

- Small n (9 tasks, 1 rep, 1 model) — directional, not a leaderboard figure.
- SWE-bench-*style*, not the official dataset (self-contained tasks, not real repos).
- The arm asymmetry (B sees tests) is intentional and = the intervention; it is not a
  bug, but it does mean this measures *gate vs no-gate*, not *Phoenix-the-brand* vs base.
- Ceiling on Tier 1 means the headline lift comes entirely from the underspecified tier
  — which is exactly where an objective gate is supposed to matter.

## Reproduce

```powershell
# validate every task's contract (F2P red + P2P green while buggy)
foreach ($t in Get-ChildItem tasks -Directory) { ... }   # see run notes

# full suite (all 9 tasks, both arms)
powershell -ExecutionPolicy Bypass -File run_swe.ps1 -Reps 1

# just the underspecified tier
powershell -ExecutionPolicy Bypass -File run_swe.ps1 -Filter "hard-*" -OutFile results_tier2.jsonl
```

Raw rows: `results.jsonl` (merged), `results_tier1.jsonl`, `results_tier2.jsonl`.
