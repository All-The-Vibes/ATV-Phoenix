---
name: phoenix-spec
description: Define what to build AND its objective acceptance check before writing code. The deliverable of this stage is not prose — it is a runnable phoenix_sense check (a test command, file hash, or regex) that will later prove the work is done. Use at the start of any non-trivial task, or when the user says /phoenix-spec.
license: MIT
---

# phoenix-spec — spec before code, with a verifiable acceptance gate

The Phoenix lifecycle is verification-first: **before** building anything, define how you will
*objectively* know it is done. A spec without a runnable check is a wish.

## Produce these, in order
1. **Goal (world-state):** the observable end-state — "X is true", not "do X".
2. **Acceptance check (the gate):** a concrete `phoenix_sense` check that passes iff the goal is met.
   Prefer `command_exit` (a test/build/lint command). Write it down as JSON:
   ```json
   {"kind":"command_exit","target":["pytest","-q","tests/test_feature.py"],"expect":0}
   ```
   If no test exists yet, the FIRST build step is to write one (the check defines "done").
3. **Constraints:** privacy, budget (calls/$), reversibility, scope (what is explicitly out).

## Rule
Do not proceed to `phoenix-plan` until the acceptance check is something you could run today and
watch fail (red on the unbuilt feature). A gate that cannot fail measures nothing.

## Honesty
If success genuinely cannot be made objective (pure judgment call), say so explicitly and name the
weakest objective proxy you can — never pretend a vibe is a verified outcome.
