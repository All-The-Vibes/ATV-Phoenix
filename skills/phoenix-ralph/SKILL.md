---
name: phoenix-ralph
description: Persistence loop that keeps working a backlog until the goal is OBJECTIVELY proven done — not until the agent thinks it's done. Wraps Geoffrey Huntley's Ralph loop (fresh context per iteration, filesystem as memory) with Phoenix's failure-first gate ledger, so completion is derived from the tamper-evident trace, never self-reported. Use when a task must run to completion across many iterations, when the user says /phoenix-ralph, "ralph", "don't stop", "keep going until it's done", or "run until the tests pass". Not for one-shot fixes (use phoenix-build) or scoping a vague idea (use phoenix-goal).
license: MIT
---

# phoenix-ralph — the persistence loop, gated by objective proof

Ralph (Geoffrey Huntley, [ghuntley.com/ralph](https://ghuntley.com/ralph)) is a dead-simple, powerful
idea: run the agent in a loop with a fixed prompt and a **fresh context every iteration**, with the
**filesystem as the only memory**. One task per loop. Huntley's original is literally
`while :; do cat PROMPT.md | agent; done`.

Phoenix adds the one thing Ralph (and Claude Code's ralph, and every "autonomous" loop) lacks: an
**objective, tamper-evident completion proof**. The loop does not stop when the agent *says* it's
done — it stops when the driver *proves* the top-level acceptance check is **failure-first satisfied**
(`phoenix-mcp accept`): the trace shows the check went **red → green** for the same check, the chain
is intact, and it is **green right now**.

> Every other persistence loop ends in an opinion ("the reviewer approved", "the model thinks it's
> done"). phoenix-ralph ends in evidence.

## How it runs

The loop lives **outside** the agent, in `dist/ralph/phoenix-ralph.ps1` (+ a bash twin), because
`copilot -p` and Scout are one-shot — there is no in-host re-injection hook. The agent proposes state
changes each iteration; **the driver decides**.

```
 driver: accept(done-check)?  ── proven green ──▶  DONE  (driver writes completed.json + git tag)
        │ not yet
        ▼
 copilot -p PROMPT.md      (fresh context; agent reads backlog.json + progress.md, does ONE item)
        │
 verify-trace intact?      ── broken ──▶ STOP (tamper/corruption)
        │ ok
 state changed?            ── no, N×  ──▶ STOP (stuck = planning problem)
        └──────────────────── loop ◀────────────
```

## State (the brain, on disk — `.phoenix-ralph/`)
- `PROMPT.md` — fixed per-loop instructions (scaffold from `dist/ralph/PROMPT.template.md`).
- `backlog.json` — `[{id, title, priority, done, check}]`. **Each item's `check` is an objective
  Phoenix check**, not prose. This is the differentiator over Huntley's `fix_plan.md` (a bullet list)
  and Claude Code's PRD (LLM-reviewed criteria).
- `progress.md` — append-only learnings; the working memory that survives the fresh context.
- `done-check.json` — the single top-level acceptance check (a real `command_exit`).
- `completed.json` — the proof bundle, written by the **driver** on success. Never by you.

## What you (the agent) do each iteration

1. **Re-read** `backlog.json` + `progress.md` first — you have amnesia between loops.
2. **Pick one** highest-priority item with `done:false`.
3. **Search before building** — code search is non-deterministic; "not found" ≠ "not done". Use
   `phoenix-context` (the graph), not blind grep.
4. **Reproduce the failure first**: `phoenix_sense` the item's `check`. It must be RED now. *This is
   what makes the gate real* — a check never seen failing is rejected by `accept`.
5. **Implement** the smallest full change (no placeholders). `phoenix_snapshot` before risky edits.
6. **Verify**: `phoenix_sense` again. Red → `phoenix_heal` (≤3) or fix; never proceed on red.
7. **Record**: set `done:true` only after red→green; append what you did + learnings to `progress.md`.
8. **Check the goal**: `phoenix_sense` the done-check. The driver independently proves it and stops.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll mark the item done; I'm sure it works." | The driver derives done from the trace. An unproven `done:true` is ignored — and dishonest edits break the hash chain. |
| "The check passes already, I'll skip reproducing the failure." | A check never seen red is vacuous; `accept` rejects it. Watch it fail first, or it proves nothing. |
| "I'll write `completed.json` / tag it to finish faster." | Only the driver writes those, only on a proven `accept`. Faking them changes nothing and corrupts state. |
| "I'll do three items this loop to save iterations." | One task per loop keeps the context fresh and the trace legible. Batching is how loops go off the rails. |
| "It's been failing the same way for 5 loops, I'll keep trying." | A stuck item is a planning problem. Record the blocker and stop; grinding burns tokens. |

## Red Flags — stop
- You're about to set `done:true` without having watched the item's check go red → green. → Reproduce first.
- You're writing `completed.json` or `git tag`. → That's the driver's job; you can't fake completion.
- The backlog item's `check` is something like `test -f file` or matches text already present. → Vacuous gate; make it a real `command_exit` that exercises the behavior.
- You're re-reading the 4th file to recall what you did last loop. → It belongs in `progress.md`; write it there.
- The same check has been red for 3 iterations. → Stop; re-plan (`phoenix-plan`), don't grind.

## Relationship to the other skills
phoenix-ralph is the **persistence wrapper**. It drives `phoenix-build`/`phoenix-test`/`phoenix-debug`
one item at a time. To turn a *vague goal* into a backlog + a real acceptance check first, use
**phoenix-goal**, which scopes the work and then hands off to this loop.
