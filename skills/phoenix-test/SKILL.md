---
type: Phoenix Skill
name: phoenix-test
description: Drive development and bug-fixing with tests where the test IS the objective phoenix_sense gate. Write a failing test before the code, reproduce a bug with a test before fixing it, and let phoenix_sense decide pass/fail — never "looks right". Use when implementing logic, fixing a bug, changing behavior, or when the user says /phoenix-test, "write tests", or "TDD".
license: MIT
---

# phoenix-test — the test is the gate; red→green is proven, not asserted

## Overview
Write a failing test before the code that makes it pass. For a bug, reproduce it with a test before
attempting a fix. In Phoenix, the test is not a suggestion — it is the literal `phoenix_sense` check
that gates the work. "Seems right" is never done; a red→green transition you watched happen is. A
codebase with tests is the agent's superpower because it converts judgment into objective signal.

## When to use
- Implementing any new logic or behavior.
- Fixing any bug (the **Prove-It Pattern** below).
- Modifying existing functionality or adding edge-case handling.

**When NOT to use:** pure config/doc/static changes with no behavioral impact (a lint sense is enough).

## The cycle — RED → GREEN → REFACTOR, each step a phoenix_sense

```
   RED                    GREEN                  REFACTOR
 write a test        write minimal code        clean up, no
 that FAILS    ──►    to make it pass     ──►   behavior change   ──► (repeat)
     │                     │                         │
 phoenix_sense        phoenix_sense             phoenix_sense
   = ok:false           = ok:true              = still ok:true
```

### 1. RED — write the failing test, and *sense it fail*
A test that passes immediately proves nothing. Run it and confirm red:
```
phoenix_sense {"kind":"command_exit","target":["pytest","-q","tests/test_task.py::test_create"],"expect":0}
# -> {"ok":false}   ← REQUIRED. If this is green, the test isn't testing the new behavior.
```

### 2. GREEN — minimal code, then sense it pass
Write the least code that turns the check green. Don't over-engineer. Re-sense the same check → `ok:true`.

### 3. REFACTOR — improve with the check as a guardrail
`phoenix_snapshot` the file, refactor, `phoenix_sense` after each change. If a refactor goes red,
`phoenix_heal rollback` — the refactor is supposed to be behavior-preserving, so red means you changed
behavior. Roll back and try a smaller refactor.

## The Prove-It Pattern (bug fixes)
When a bug is reported, **do not start by fixing it.** Start by reproducing it as a test:
```
Bug report ─► write a test that reproduces it ─► phoenix_sense = ok:false (bug confirmed)
           ─► fix the code ─► phoenix_sense = ok:true (bug fixed, and now regression-guarded forever)
```
The failing test does three jobs: it proves the bug exists, proves your fix works, and prevents the bug
from coming back. A "fix" with no reproducing test is a guess.

## Token-efficiency note
Run the **narrowest** check that proves the step (a single test id), not the whole suite, during the
inner loop — fast feedback, cheap tokens. Sense the full suite once at the end (and in `phoenix-review`).

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll write the test after the code." | Test-after rarely fails first, so it proves nothing and often just encodes the bug you shipped. |
| "I can see the test would pass, no need to run RED." | A test you didn't watch fail might be testing nothing (typo'd assertion, wrong import). Sense the red. |
| "This bug is obvious, I'll just patch it." | ~30% of "obvious" fixes are wrong or incomplete. A reproducing test is the cheap insurance. |
| "The test is flaky, I'll skip it." | Flaky tests mask real bugs. `phoenix_heal retry` to see if it's transient; if it's real, fix it. |
| "Refactor doesn't need re-testing." | Refactor means behavior-preserving — the only way to *know* it preserved behavior is to sense the test green. |

## Red Flags
- A new test passed on the first run. → It probably isn't exercising the new behavior. Make it fail first.
- You're fixing a bug with no reproducing test. → Write the test; sense it red before you fix.
- You edited the test to match the code's current (wrong) output. → That's encoding the bug. Revert.
- You only ever run the full suite. → Use a narrow check in the inner loop for cheap, fast feedback.

## Next
With the behavior proven, continue in **`phoenix-build`** for remaining steps, or **`phoenix-review`**
when the feature is complete. A red you can't explain → **`phoenix-debug`**.
