---
name: phoenix-build
description: Build one planned step at a time under the verify-heal loop — snapshot before risky edits, sense after, heal if broken. Never advance to the next step on a red check. Use during implementation, or when the user says /phoenix-build.
license: MIT
---

# phoenix-build — one slice at a time, always green before advancing

Implement the plan's steps under the Phoenix self-heal loop. The discipline: the build stays green
between steps, and you never *believe* it is green — you `phoenix_sense` it.

## Per step
1. **Snapshot** the file(s) you will edit if the step is risky: `phoenix_snapshot(path, check)`
   (it only blesses a known-good state).
2. **Edit** — the smallest change that should satisfy this step's check.
3. **Sense** — `phoenix_sense(step_check)`. If `ok` is false, you broke it or didn't finish it.
4. **Heal** — `phoenix_heal` (rollback to the snapshot, or retry, or fix-and-re-sense). Trust the
   external recheck, not your own read of the diff.
5. Advance only when the step's check is green.

## Rules
- Bounded: do not loop forever on a step. After a few failed heals, stop and report what is blocking —
  a stuck step is a planning problem, not a grinding problem.
- Surgical: change only what the step needs; unrelated edits break unrelated checks.

## Honesty
A step is done when its check is green — not when the code "looks right". Report `unknown`, never a
fabricated pass.
