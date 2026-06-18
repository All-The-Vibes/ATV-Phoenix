---
type: Phoenix Skill
name: phoenix-self-heal
description: The core verify-then-heal loop usable on its own for any change with a checkable outcome — sense success objectively, snapshot known-good state, and recover (bounded rollback or retry) when a check goes red, confirmed by an external recheck. Use whenever you make a change that has a runnable test/build/lint, or when the user says /phoenix-self-heal, "verify and fix", or "make sure it works".
license: MIT
---

# phoenix-self-heal — sense, snapshot, heal; the loop at the heart of Phoenix

## Overview
This is the primitive every Phoenix lifecycle skill is built on, usable standalone: objectively **sense**
whether work succeeded, keep a blessed **snapshot** to fall back to, and **heal** (bounded) when a check
goes red — with recovery confirmed by an independent recheck, never by self-judgment. It gives an agent
the one organ it's missing: knowing it failed, and fixing it, with evidence.

## When to use
- Any code change with a runnable check (test/build/lint).
- Risky edits where you want a guaranteed rollback point.
- As the inner loop of `phoenix-build`, `phoenix-test`, and `phoenix-debug`.

## The four tools
- **phoenix_sense(check)** — objective check. `kind` ∈ `command_exit` (run argv, pass iff exit==expect,
  default 0), `file_sha256`, `regex_in_file`. Returns `{ok, signal, evidence}`. No LLM, no opinion.
  `target` accepts an argv array (preferred) or a string; `expect` accepts an int or string.
- **phoenix_snapshot(path, check)** — save `path` as last-good **only if `check` passes** (never blesses
  a broken state). Returns `{blessed, snap_id}`.
- **phoenix_heal(strategy, ctx)** — `rollback` (restore a blessed snapshot) or `retry` (re-run a command
  ≤3×). `healed=true` only if `ctx.recheck` passes **after** the action. Bounded; reversible.
- **phoenix_verify_trace()** — audit the tamper-evident hash-chained log.

## Example
```
{"check":{"kind":"command_exit","target":["pytest","-q"],"expect":0}}                       # sense
{"path":"src/app.py","check":{"kind":"command_exit","target":["pytest","-q"],"expect":0}}    # snapshot (blesses if green)
{"strategy":"rollback","ctx":{"path":"src/app.py","snap_id":"app.py.1a2b…",                    # heal
  "recheck":{"kind":"command_exit","target":["pytest","-q"],"expect":0}}}
```

## The loop

```
  baseline ─► phoenix_sense ─► ok? ──no──► (not ready; create a check first)
                               │ yes
                               ▼
                       phoenix_snapshot (bless green state)
                               │
                               ▼
                          ── edit ──
                               │
                       phoenix_sense ─► ok? ──yes──► done (green, proven)
                               │ no
                               ▼
                       phoenix_heal (rollback/retry, ≤3) ─► re-sense ─► green? 
                               │ no after 3 → STOP, report what's blocking
```

## Rules
- **Snapshot only blesses green.** You can never accidentally save a broken state as your fallback.
- **Heal is confirmed externally.** `healed=true` requires the independent `recheck` to pass *after* the
  action — the heal never grades itself.
- **Bounded.** ≤3 attempts, then stop and report. Unbounded healing is token-burning, not progress.
- **Reversible by default.** Rollback restores a blessed snapshot atomically; nothing is destroyed
  without a known-good point to return to.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll just check the output myself." | Your read of the output is self-grading. `phoenix_sense` is the objective signal; use it. |
| "Snapshot is overkill for this edit." | The edit you don't snapshot is the one that breaks three files. It costs one call; the regret costs an hour. |
| "Keep healing until it's green." | After 3 attempts you're masking a deeper problem. Stop, report, re-plan. |
| "It healed because the file looks right now." | "Looks right" isn't healed. `healed=true` only when the external recheck is green. |

## Red Flags
- Claiming success with no `phoenix_sense`. → Run the check.
- Editing without a snapshot on a risky change. → Snapshot the blessed state first.
- 4th heal attempt. → Stop; this is a planning problem (`phoenix-plan`) or a real bug (`phoenix-debug`).
- Trusting "healed" without the external recheck. → Confirm green via the recheck, not the diff.

## Next
Standalone, this is enough to verify-and-fix one change. For full work, route through the lifecycle:
`phoenix-think → plan → build (↔ test/debug) → review → ship`.
