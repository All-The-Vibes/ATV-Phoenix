---
name: phoenix-craft
description: Code-craft guardrails that reduce the most common LLM coding mistakes — think before coding, simplicity first, surgical changes, and verifiable success — gated by objective phoenix_sense checks so "simpler" and "done" are proven, not asserted. Grounded in Andrej Karpathy's observations on LLM coding pitfalls. Use when writing, refactoring, or reviewing any code, or when the user says /phoenix-craft, "keep it simple", or "don't over-engineer".
license: MIT
---

# phoenix-craft — write less, change less, prove more

> Encodes [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM
> coding pitfalls, wired into Phoenix's verify-heal discipline. Biases toward caution over speed; for
> trivial tasks, use judgment.

## Overview
LLMs fail at code in predictable ways: they over-build, "improve" code they were never asked to touch,
silently pick one interpretation of an ambiguous ask, and declare success without proof. `phoenix-craft`
is the antidote — four habits, each backed by an objective `phoenix_sense` check so the virtues are
*measured*, not merely intended.

## The four habits

### 1. Think before coding
Don't assume; don't hide confusion; surface tradeoffs.
- State assumptions explicitly. If uncertain, ask (`phoenix-think`).
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop, name what's confusing, ask.

### 2. Simplicity first
Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked. No abstractions for single-use code.
- No "flexibility"/"configurability" that wasn't requested. No error handling for impossible cases.
- If you wrote 200 lines and it could be 50, rewrite it.
- The test: *would a senior engineer call this overcomplicated?* If yes, simplify — **then re-run the
  acceptance `phoenix_sense` to prove the simpler version still passes.** Simplicity that breaks the
  check isn't simpler, it's broken.

### 3. Surgical changes
Touch only what you must; clean up only your own mess.
- Don't "improve" adjacent code, comments, or formatting. Don't refactor what isn't broken.
- Match existing style even if you'd do it differently.
- Remove imports/vars/functions **your** change orphaned; leave pre-existing dead code (mention it).
- The test: *every changed line traces directly to the request.* Verify the diff is minimal before
  sensing — a bloated diff breaks unrelated checks and pollutes the blast radius.

### 4. Verifiable success
"Seems right" is not done. Define the objective check up front (`phoenix-think`) and gate completion on
it (`phoenix-ship`). Craft without a check is just confident guessing.

## How it composes with Phoenix
- **Think** → `phoenix-think` (deep interview when the ask is vague).
- **Simplicity/surgical** are *behaviors during* `phoenix-build`; the `phoenix_sense` gate keeps them honest.
- **Verifiable success** is enforced by `phoenix-ship` (green acceptance check + verified trace).

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll add config/flexibility now so it's future-proof." | Speculative flexibility is dead weight you'll maintain forever. Build for the ask; add flexibility when a second caller actually appears. |
| "While I'm here, I'll tidy this nearby code." | That's an unrequested change that breaks unrelated checks and bloats review. Mention it; don't touch it. |
| "The simpler version is probably fine, ship it." | "Probably" isn't proof. Re-run the acceptance `phoenix_sense` — simpler must still be green. |
| "There are two ways to read this; I'll pick one." | Silent interpretation is the #1 LLM failure. Surface both, let the user choose. |
| "More error handling can't hurt." | Handling impossible cases is noise that hides the real paths and inflates the diff. Handle the failures that can actually happen. |

## Red Flags
- The diff touches files unrelated to the request. → Trim to surgical; every line traces to the ask.
- You added an abstraction with exactly one caller. → Inline it; abstract on the second use.
- You picked one meaning of an ambiguous ask silently. → Stop; surface the interpretations.
- You simplified but didn't re-sense. → A refactor is behavior-preserving only if the check stays green.

## Next
Pair with `phoenix-build` (surgical implementation under the heal loop), `phoenix-typescript` (type-level
craft), and `phoenix-ship` (verifiable done).
