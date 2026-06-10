---
name: phoenix-plan
description: Decompose a clear intent into small, individually-verifiable steps before writing code — each step a slice you can prove pass/fail with phoenix_sense, ordered so the build stays green between them. Use after phoenix-think, when you have an Intent Contract and need an executable plan, or when the user says /phoenix-plan, "break this down", or "make a plan".
license: MIT
---

# phoenix-plan — small atomic steps, each with an objective finish line

## Overview
A plan is only useful if you can *prove* each step is done. Phoenix plans in **slices the self-heal
loop can verify one at a time** — every step carries its own `phoenix_sense` check, the steps compose
up to the Intent Contract's acceptance gate, and the build stays green between them so any step is
independently revertible. A plan whose steps you can't check is a wish list.

## When to use
- After `phoenix-think` produced an Intent Contract with an acceptance check.
- Any multi-step change, refactor, or feature where order and blast radius matter.
- When a task "feels big" — planning is how you find the seams.

**When NOT to use:** a one-line change with an obvious check — just `phoenix-build` it directly.

## The planning flow

```
Intent Contract (acceptance check)
        │
        ▼
  Decompose into ordered slices
        │
        ▼  for each slice:
  ┌─────────────────────────────┐
  │ goal (one line)             │
  │ check (a phoenix_sense)     │  ← must be runnable & able to fail
  │ risky? → snapshot first     │
  └─────────────────────────────┘
        │
        ▼
  Slices compose up to the acceptance check
```

## Produce a step list like this
```
STEP 1  Add the failing test for the new behavior
        check: {"kind":"command_exit","target":["pytest","-q","tests/test_x.py::test_new"],"expect":0}
        (expected RED until step 2 — that's correct)
STEP 2  Implement the minimal code to pass step 1   risky? no
        check: same as step 1, now expected GREEN
STEP 3  Wire it into the caller                       risky? YES → snapshot caller.py first
        check: {"kind":"command_exit","target":["pytest","-q"],"expect":0}  (full suite green)
ACCEPTANCE  = step 3's full-suite check (from the Intent Contract)
```

## Rules
- **One check per step.** If you can't attach a single objective check to a step, it's too big — split it.
- **Green between steps.** Order so the suite is green after each step; that makes every step revertible
  and turns "it broke" into "roll back the last step", not "debug the whole change".
- **Name the risky steps.** Steps likely to break a passing check get a `phoenix_snapshot` before editing
  so `phoenix_heal` can roll back instantly.
- **Use the graph to scope.** Before planning a change to `X`, ask `phoenix-context` "what breaks if I
  change X?" — plan the real blast radius, not a guessed one. (Cheaper and more accurate than grepping.)
- **The last step's check = the acceptance gate.** The plan is wrong if the steps don't compose up to it.

## Sizing heuristic
A good step is one you could implement and verify in a single focused pass. If a step needs "and then
also…", that's two steps. Smaller steps = tighter heal granularity = less wasted work on a failure.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll plan it in my head and just build." | Unwritten plans have no verifiable steps; the first surprise becomes a debugging spiral. Write the checks down. |
| "This step is too small to need its own check." | A step without a check can't be healed in isolation — when it breaks you bisect the whole change. |
| "I'll figure out the blast radius as I go." | "As you go" means re-reading files every turn. Ask the graph once, plan the real scope. |
| "I'll snapshot later if I need to." | You need the snapshot *after* you've already overwritten the good state. Snapshot before the risky edit. |

## Red Flags
- A step has no runnable check. → Split or rewrite it until it does.
- The suite would be red between two steps. → Reorder so green is the resting state.
- You're guessing what a change affects. → `phoenix-context` the blast radius first.
- The plan has one giant "implement the feature" step. → That's not a plan; decompose it.

## Next
Hand each step to **`phoenix-build`** (snapshot→edit→sense→heal). For "prove this behavior" steps, route
to **`phoenix-test`**.
