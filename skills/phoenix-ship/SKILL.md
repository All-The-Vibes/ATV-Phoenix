---
type: Phoenix Skill
name: phoenix-ship
description: The final gate before declaring a task done — run the acceptance check one last time, verify the tamper-evident trace is intact, and report success only on green evidence with the proof attached. Use as the last step of any task, before merging or telling the user it's complete, or when the user says /phoenix-ship, "ship it", or "is it done".
license: MIT
---

# phoenix-ship — declare done only on green evidence

## Overview
This is the last line of defense against shipping silently-broken work. "Done" is not a feeling or a
diff that looks right — it is a green `phoenix_sense` on the acceptance check plus an intact trace that
proves the green is real. Phoenix exists to prevent exactly one failure: an agent confidently saying
"done" on work that doesn't actually work. This skill is where that promise is kept.

## When to use
- The final step of any task, right before you tell the user it's complete or merge.
- Whenever you're about to type "done", "fixed", "ready", or "shipped".

## The ship gate

```
  About to say "done"
       │
       ▼
  1. phoenix_sense(acceptance_check)   ──► must be ok:true
       │                                       │ red?
       ▼                                       ▼
  2. phoenix_verify_trace              ──► STOP. Not done. → phoenix-debug
       │  ok + intact chain?
       ▼
  3. Report WITH evidence (check + trace head hash)
       │
       ▼
       DONE (provably)
```

### 1. Final acceptance sense
`phoenix_sense(acceptance_check)` from the Intent Contract (`phoenix-think`). Green is mandatory. Not
"the test I added" — the **acceptance** check that represents the user's actual definition of success.

### 2. Verify the trace
`phoenix_verify_trace` → `ok:true` with an intact hash chain. This proves the green you're about to
report is genuine and wasn't reached by skipping or editing a gate. A broken chain means you are **not**
done, no matter how the code looks.

### 3. Report with the evidence attached
State the check that passed and the trace head hash, so the claim is auditable:
> "Done — `pytest -q` exits 0 (acceptance check); trace verified, 14 rows, head `9885e6df…`."

That one line is the difference between a trustworthy completion and a hopeful one.

## The rule that is the whole point
**Never type "done" without a green `phoenix_sense`.** If the check is red or the trace is broken, you
are not done — say exactly what is failing and route to `phoenix-debug`. "I'm not sure it passed" is an
acceptable, honest status; a fabricated completion is the cardinal failure this entire harness exists to
prevent.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It's obviously done, I'll just say so." | "Obviously done" with no green check is exactly the silent failure Phoenix measured at 40% on real tasks. Run the check. |
| "The new test passed, that's enough." | The new test ≠ the acceptance criteria. Sense the *acceptance* check; that's the user's definition of done. |
| "I'll skip the trace check, it's fine." | The trace is your proof the gate wasn't skipped. It's one call and it's what makes "done" auditable. |
| "Close enough, I'll note the caveat." | If there's a real caveat, the work isn't shipped — it's shipped-with-a-known-bug. Say that plainly, don't bury it. |

## Red Flags
- Typing "done"/"fixed"/"ready" with no green `phoenix_sense` in this session. → Run the acceptance check now.
- Reporting success without the trace verified. → Verify it; unverified green is just a hope.
- Reporting the new test instead of the acceptance check. → Sense the acceptance gate.
- A known issue you're shipping quietly. → Surface it explicitly; never bury a caveat in optimism.

## Done means
Acceptance check green + trace verified + evidence reported. Anything less is "in progress", and saying
otherwise is the one thing Phoenix forbids.
