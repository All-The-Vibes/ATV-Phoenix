---
name: phoenix-review
description: Review completed work against the spec's acceptance criteria using objective evidence, not opinion. Re-run every check, inspect the trace, and surface only real issues (bugs, broken criteria, regressions). Use before shipping, or when the user says /phoenix-review.
license: MIT
---

# phoenix-review — evidence-based review, not vibes

Before shipping, prove the work meets the spec — objectively.

## Do
1. **Re-run the acceptance gate** from `phoenix-spec`: `phoenix_sense(acceptance_check)` → must be green.
2. **Re-run each step check** (or the full test/build) — confirm no step regressed another.
3. **Inspect the trace:** `phoenix_verify_trace()` — confirm the chain is intact and shows a real
   green→(work)→green path, not a skipped check.
4. **Surface only real issues:** bugs, unmet acceptance criteria, regressions. Do NOT raise style or
   taste nits — Phoenix reviews *correctness*, the model already handles style.

## Rule
If any check is red or the trace is broken, the work is NOT review-passed — send it back to
`phoenix-build`. A green review requires green evidence.
