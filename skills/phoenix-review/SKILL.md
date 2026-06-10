---
name: phoenix-review
description: Review completed work against the Intent Contract's acceptance criteria using objective evidence, not opinion — re-run every check, confirm no regressions, inspect the tamper-evident trace, and surface only real issues (bugs, unmet criteria, regressions). Use before shipping, after a feature is built, or when the user says /phoenix-review or "review this".
license: MIT
---

# phoenix-review — evidence-based review, not vibes

## Overview
Before anything ships, prove it meets the intent — objectively. A Phoenix review is not a re-read of
the diff hoping to spot problems; it re-runs the checks, confirms nothing else regressed, and inspects
the trace to confirm the green you see is real and was reached honestly. It surfaces **correctness**
issues only — the model already handles style; Phoenix reviews whether the work actually works.

## When to use
- A feature/step set is "done" and headed for `phoenix-ship`.
- Before merging or handing off.
- After a non-trivial `phoenix-build` or `phoenix-debug` session.

## The review gate

```
  Completed work
       │
       ▼
  1. Re-run the ACCEPTANCE check (from phoenix-think)   → must be green
       │
       ▼
  2. Re-run the FULL suite/build/lint                   → no regressions
       │
       ▼
  3. phoenix_verify_trace                               → chain intact, real green→work→green
       │
       ▼
  4. Surface ONLY real issues (bugs / unmet criteria / regressions)
       │
       ▼
  green evidence ─► phoenix-ship      any red / broken trace ─► phoenix-debug
```

### 1. Re-run the acceptance gate
`phoenix_sense(acceptance_check)` from the Intent Contract. If it isn't green, the work is not
review-passed — full stop. Send it back to `phoenix-build`/`phoenix-debug`.

### 2. Check for regressions
Sense the **full** suite/build/lint, not just the new test. The most common review miss is a change
that satisfies its own check while breaking something adjacent. Use `phoenix-context` `impact` to
confirm you tested everything in the blast radius.

### 3. Inspect the trace
`phoenix_verify_trace` must report `ok:true` with an intact hash chain showing a genuine
green→(work)→green path. A broken chain, or a "green" with no prior red, means the gate was skipped or
the evidence was edited — treat that as a failed review.

### 4. Surface only what matters
Raise: unmet acceptance criteria, bugs, regressions, security/correctness risks, missing error handling
on a real failure path. **Do not** raise style, naming taste, or formatting nits — that's noise, and
the model handles it already. High signal-to-noise is the whole value of the review.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The new test passes, so it's good." | The new test passing says nothing about the 200 other tests your change might have broken. Run the full suite. |
| "I read the diff, it looks fine." | Reading a diff is self-grading. Re-run the checks; evidence, not eyeballs, gates a review. |
| "The trace is probably fine, skip it." | The trace is how you know the green wasn't faked or the gate skipped. Verify it — it's one call. |
| "I'll note these style nits too." | Style nits drown the real issues. Review correctness; let the model handle taste. |

## Red Flags
- Acceptance check not re-run. → Re-run it; that's the whole gate.
- Only the new test was run. → Run the full suite for regressions.
- Trace shows green with no preceding red. → The gate was skipped; the evidence is suspect.
- The review is mostly style comments. → Refocus on correctness; cut the nits.

## Next
Green evidence → **`phoenix-ship`**. Any red, regression, or broken trace → **`phoenix-debug`**.
