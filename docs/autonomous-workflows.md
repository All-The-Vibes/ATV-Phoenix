# Autonomous workflows on Phoenix: ralph, goal, and dynamic routing

How Phoenix delivers the same autonomous-execution capabilities as Claude Code's `ralph` / `autopilot`
— **the Ralph persistence loop, goal-oriented execution, and dynamic workflows** — but gated by
Phoenix's objective, tamper-evident verification instead of an LLM's opinion.

Grounded in primary research: Geoffrey Huntley's Ralph ([ghuntley.com/ralph](https://ghuntley.com/ralph)),
Anthropic's [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
and [SWE-bench scaffold](https://www.anthropic.com/research/swe-bench-sonnet), BabyAGI, and ReAct. Full
report with citations: [`research/autonomous-workflows-research.md`](../research/autonomous-workflows-research.md).

---

## The one idea that makes Phoenix's version different

Every autonomous loop in the wild ends in a **subjective** stop signal:

- Huntley's Ralph: a human watches the stream and kills the loop; or "tests pass" as *claimed* by the agent.
- Claude Code's `ralph`/`autopilot`: an **architect/critic agent approves** (an LLM judging an LLM).
- BabyAGI: there is *no* reliable `goal_achieved()` — it can loop forever.

Phoenix replaces the stop signal with an **objective, tamper-evident, failure-first proof**:

> A task is done when the tamper-evident trace shows its acceptance check went **red → green** for the
> *same* check, the hash chain is intact, and the check is **green right now** — proven by
> `phoenix-mcp accept`, run by the driver, not authored by the agent.

This is the SWE-bench discipline ("create a reproduce script, confirm it fails, fix, confirm it passes")
turned into a tooling-enforced gate. A check that was *never seen failing* (a vacuous `test -f file`)
proves nothing and is rejected.

---

## The gate ledger (`phoenix-mcp accept`)

The new spine primitive that the whole feature rests on. Given a check, it derives completion from the
trace:

```
accept(check) = trace_intact            (hash chain verifies)
              AND saw_red               (a RED sense of THIS exact check exists)
              AND green_after_red       (a GREEN sense of it exists later)
              AND currently_green       (re-running it now passes)
```

Checks are identified by a **canonical digest** (`canonical_digest(&Check)`) — the same for a command
passed as `"pytest -q"` or `["pytest","-q"]`, and recorded identically in the MCP path, the CLI path,
and the ledger — so "this exact check went red then green" is provable across the log.

```
$ phoenix-mcp accept @.phoenix-ralph/done-check.json
{"ok":false,...,"saw_red":false,"reason":"no RED observation for this check in the trace —
 a gate never seen failing proves nothing (vacuous-check guard)..."}     # exit 1

# after the loop reproduced the failure and fixed it:
{"ok":true,"saw_red":true,"green_after_red":true,"currently_green":true,
 "reason":"failure-first satisfied: red→green in an intact trace, currently green"}   # exit 0
```

(Proven by `tests/gate_ledger.rs`: accepts real red→green, rejects never-red/vacuous, rejects a
tampered trace.)

---

## 1. The Ralph loop — `phoenix-ralph`

Huntley's loop is `while :; do cat PROMPT.md | agent; done`: fresh context every iteration, the
filesystem is the brain, one task per loop. Phoenix ships exactly this as an **external driver**
([`dist/ralph/phoenix-ralph.ps1`](../dist/ralph/phoenix-ralph.ps1) + a bash twin) — external because
`copilot -p` and Scout are one-shot and have no Claude-Code-style "re-inject the prompt" hook, so the
loop *is* the persistence.

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

**State** (`.phoenix-ralph/`): `PROMPT.md` (fixed instructions), `backlog.json` (items, each with an
**objective** `check`), `progress.md` (append-only memory across the amnesiac loops), `done-check.json`
(the top-level acceptance check), `completed.json` (driver-written proof bundle).

**The driver owns the decisions** (the rubber-duck's key fix): loop/wall-clock budget, the pre-turn
accept, the trace-intact check, no-progress detection, and the proof bundle + tag. The agent *proposes*
state changes (edits files, sets `done:true`); the driver *proves* them. An agent that lies in
`backlog.json` changes nothing — completion is derived from the trace, and tampering breaks the chain.

Skill: [`skills/phoenix-ralph`](../skills/phoenix-ralph/SKILL.md). Compare to Huntley's `fix_plan.md`
(prose bullets) and Claude Code's `prd.json` (LLM-reviewed criteria): Phoenix's backlog items carry
**objective checks**, and the final gate is **machine-proven**, not reviewed.

## 2. Goal-oriented execution — `phoenix-goal`

One fuzzy goal → a proven outcome. The critical, non-skippable first step is **FORMALIZE**: derive an
*executable acceptance check* before any code — because (per BabyAGI/ReAct) a goal with no objective
criterion has no honest termination.

```
fuzzy goal → phoenix-think (interview+research) → done-check.json (a real command_exit, starts RED)
           → phoenix-plan (decompose) → backlog.json (each item an objective check)
           → hand to phoenix-ralph → driver proves done-check failure-first → DONE
```

The acceptance check is **authored during FORMALIZE and frozen before implementation**, so the loop
satisfies the gate rather than weakening it. Changing the gate is a re-scope (back to `phoenix-think`,
re-baseline the new check as red). Skill: [`skills/phoenix-goal`](../skills/phoenix-goal/SKILL.md).

This is the Phoenix realization of the Intent-to-Outcome loop's "intent → verifiable acceptance
criteria → outcome" (see [`intent-to-outcome.md`](intent-to-outcome.md)).

## 3. Dynamic workflows — `phoenix-auto`

Where the base `phoenix` skill is a **fixed** routing tree, `phoenix-auto` is the **dynamic** one
(Anthropic's *routing* + *orchestrator-workers*): each step senses current state (green/red, stage, is
there a backlog) and picks the next skill at runtime, because real work's subtasks aren't predictable.

Guardrails against the known dynamic-routing failure modes: an **oscillation guard** (stop if it bounces
between skills or repeats with no state change), a **confidence fallback** to `phoenix-think`, **re-sense
don't cache**, a **step cap**, and — unchanged — **every executed step still ends in an objective
`phoenix_sense` gate**. Skill: [`skills/phoenix-auto`](../skills/phoenix-auto/SKILL.md).

It's **opt-in**: the base `phoenix` router stays a stable fixed tree and dispatches to `phoenix-auto`
only when you ask for autonomous mode or `.phoenix-ralph/` state is present (so the simple, predictable
routing nobody should have to think about doesn't regress).

---

## How the three compose

```
phoenix-auto  (dynamic router: pick the mode)
    ├── vague goal  ─────────────▶  phoenix-goal  (FORMALIZE the acceptance check + DECOMPOSE)
    │                                    └── hands off to ▶ phoenix-ralph
    └── have a backlog  ─────────▶  phoenix-ralph (persistence loop)
                                         └── drives ▶ phoenix-build / phoenix-test / phoenix-debug
                                         └── completion proven by ▶ phoenix-mcp accept (gate ledger)
```

Same as Claude Code's `autopilot ⊃ ralph ⊃ ultrawork` nesting — but every "done" is evidence, not an
opinion.

---

## Honest limits
- The driver is the authority, but it runs the agent via `copilot -p`; cost/runaway control is the
  driver's budgets (`-MaxLoops`, `-MaxMinutes`, `-NoProgressStop`), not a hard sandbox.
- `accept` proves *a check* went red→green; it's only as meaningful as the check. The `command_exit`
  restriction for the top-level gate, and the failure-first requirement, are the guards against weak
  checks — but a determined author can still write a check that's real-looking yet shallow. Garbage
  check in, garbage proof out; the discipline is human-owned.
- Fresh-context-per-loop relies on the filesystem state being complete and re-read every iteration;
  the PROMPT enforces the re-read, and the no-progress guard catches a loop that stops advancing.
