---
name: phoenix-auto
description: Dynamic, state-sensing router for autonomous multi-step work — chooses the next Phoenix skill at runtime from the current objective state (what's green/red, what stage, is there a backlog) instead of following a fixed pipeline. Use for open-ended autonomous execution where the next step depends on results, when the user says /phoenix-auto, "drive this", "orchestrate", or "figure out the steps as you go". For a fixed lifecycle just use the phoenix meta-router; for a persistent backlog loop use phoenix-ralph.
license: MIT
---

# phoenix-auto — the adaptive orchestrator

The base `phoenix` skill is a **fixed routing tree** (think → plan → build → review → ship): great
when the path is known. phoenix-auto is the **dynamic** counterpart — Anthropic's *routing* +
*orchestrator-workers* patterns ([Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)):
at each step it **senses current state** and picks the next skill based on results, because in real
work you can't predict the subtasks up front.

> Fixed pipeline = a train on rails. phoenix-auto = a driver reading the road. Both are valid; pick by
> how predictable the path is.

## The state-sensing loop

```
            ┌───────────────────────────────────────────────┐
            ▼                                               │
   SENSE state ──▶ ROUTE to a skill ──▶ EXECUTE ──▶ phoenix_sense gate
   (green/red?      (pick next by         (run it)        │
    backlog?         current reality)                     ├─ green ─▶ snapshot, re-SENSE ─┘
    stage?)                                               └─ red  ──▶ phoenix_heal (≤3) ─▶ re-SENSE
```

### Routing policy (what to pick, given state)
| Current state | Route to |
|---|---|
| Goal is vague / no acceptance check exists | `phoenix-goal` (formalize) → or `phoenix-think` |
| Have intent, no steps | `phoenix-plan` |
| There's a backlog to grind to completion | `phoenix-ralph` (the persistence loop) |
| Implementing a known step | `phoenix-build` (+ `phoenix-test` to set the gate) |
| A check is red / something broke | `phoenix-debug` |
| Need cheap structural context | `phoenix-context` (graph) |
| Work looks complete | `phoenix-review` → `phoenix-ship` |

## Guardrails (dynamic routing fails in specific, known ways — design against them)

- **Oscillation guard.** Keep a short route history. If you route to the same pair of skills back and
  forth, or pick the same skill 3× with no state change, **stop and escalate** — that's a planning
  problem, not a routing one.
- **Confidence fallback.** If the right next skill isn't clear, route to `phoenix-think`, don't guess.
- **Re-sense, don't cache.** Decide from a *fresh* read of state (the trace, the backlog, a real
  `phoenix_sense`), never a remembered summary — stale state causes wrong routes.
- **Every executed step still ends in an objective gate.** Routing chooses *what*; `phoenix_sense`
  decides *whether it worked*. Dynamic routing never relaxes the verification law.
- **Bounded.** A cap on total steps; on exhaustion, report state honestly rather than looping.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll keep routing until it works out." | Unbounded routing is just an expensive infinite loop. Cap steps; escalate when stuck. |
| "I routed here last step, I remember the state." | Re-sense. Acting on cached state is the #1 cause of wrong routes. |
| "Confidence is low but I'll pick something." | Low confidence → `phoenix-think`. Guessing the route wastes a whole step. |
| "This step's result looks right, route onward." | "Looks right" isn't a gate. `phoenix_sense` before you route on a result. |

## Red Flags — stop
- You've bounced between two skills more than twice. → Escalate; it's a planning problem.
- You're routing based on what you *think* the state is. → Re-sense from disk/trace first.
- A step "succeeded" with no `phoenix_sense`. → No gate, no progress; verify before routing on.

## Relationship to the other skills
phoenix-auto is opt-in: the base **phoenix** router stays a stable fixed tree and dispatches here only
when you explicitly ask for autonomous mode or when `.phoenix-ralph/` state is present. For a known
backlog it will usually route straight into **phoenix-ralph**; for a vague goal, into **phoenix-goal**.
