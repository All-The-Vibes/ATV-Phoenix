---
name: phoenix-ship
description: Final gate before declaring a task done — run the acceptance check one last time, verify the tamper-evident trace, and report success ONLY on green evidence. Use as the last step of any task, or when the user says /phoenix-ship.
license: MIT
---

# phoenix-ship — declare done only on green evidence

The last line of defense against shipping silently-broken work.

## Do, in order
1. **Final acceptance sense:** `phoenix_sense(acceptance_check)` from the spec. Must be green.
2. **Verify the trace:** `phoenix_verify_trace()`. Must report `ok:true` with an intact hash chain —
   this is the evidence that the green you see is real and was not edited.
3. **Report with evidence:** state the acceptance check that passed and the trace head hash. Example:
   "Done — `pytest -q` exits 0; trace verified (12 rows, head 9885e6df…)."

## The rule that is the whole point
Never type "done" without a green `phoenix_sense`. A fabricated completion is the single failure mode
this entire harness exists to prevent. If the check is red or the trace is broken, you are NOT done —
say exactly what is failing.
