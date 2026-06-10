---
name: phoenix-plan
description: Break a spec into small, individually-verifiable steps — each with its own objective check — before building. Every step must be a slice you can sense as pass/fail. Use after phoenix-spec, or when the user says /phoenix-plan.
license: MIT
---

# phoenix-plan — small atomic steps, each verifiable

A plan is good only if each step has an objective finish line. Phoenix plans in slices that the
self-heal loop can verify one at a time.

## Produce
- An ordered list of **small steps**. For each: a one-line goal + the `phoenix_sense` check that
  proves that step is done (often a single test case or a build/lint command).
- Identify the **risky steps** (likely to break a passing check) — those get a `phoenix_snapshot`
  before editing, so `phoenix_heal` can roll back.

## Rules
- A step too big to attach a single check to is too big — split it.
- The plan's last step's check is the spec's acceptance gate (the steps must compose up to it).
- Prefer steps that keep the build green between them (so every step is independently revertible).

## Next
Hand each step to `phoenix-build`, which executes it under the verify-heal loop.
