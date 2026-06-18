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

The new spine primitive that the whole feature rests on. Available **both** as an MCP tool
(`phoenix_accept`, for the interactive in-session loop) and a CLI command (`phoenix-mcp accept`, for the
unattended driver). Given a check, it derives completion from the trace:

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
filesystem is the brain, one task per loop. Phoenix runs this in **two modes**:

**A. Interactive (inside the Copilot CLI) — the common case.** You invoke `/phoenix-ralph` in a live
session. There is **no external script**: the loop runs *in-session* as the agent's own tool-use loop
(edit → `phoenix_sense` → heal → …), and the agent does not declare done until the **`phoenix_accept`
MCP tool** proves the done-check failure-first. If work outgrows one context window, the user says
"continue" and the agent re-reads the state files and resumes.

**B. Unattended / large (`copilot -p`).** For overnight jobs, CI, or work too big for one context, the
external driver ([`dist/ralph/phoenix-ralph.ps1`](../dist/ralph/phoenix-ralph.ps1) + bash twin)
re-invokes the agent with a **fresh context every loop** (Huntley's key trick against the ~150k-token
degradation). It calls `phoenix-mcp accept` (the CLI form of the same gate) and owns the budgets,
sentinel, and tag.

Both modes share the identical law — completion is **proven** (`phoenix_accept` / `phoenix-mcp accept`:
red→green on an intact trace, green now), never self-reported. Mode B's loop:

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

One fuzzy goal → a demonstrated outcome. The critical, non-skippable first step is **FORMALIZE**: derive an
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

## Designed for long-horizon tasks (and how it aligns with Anthropic & OpenAI Codex)

`phoenix-goal + phoenix-ralph + phoenix-auto` is not three loosely-related skills — it's **one system
purpose-built for long-running, multi-hour, many-step work**. When you give it a goal, `phoenix-goal`
formalizes a persistent definition of done, `phoenix-ralph` grinds the backlog across fresh-context
iterations with the filesystem as memory, and `phoenix-auto` picks the next move dynamically. This is
the same shape both major labs have converged on for long-horizon reliability — Phoenix's contribution
is making the *completion signal* an objective, tamper-evident proof instead of a judgment.

The recurring long-horizon patterns, and where each Phoenix skill realizes them:

| Long-horizon pattern | Anthropic | OpenAI Codex | Phoenix |
|---|---|---|---|
| **A persistent "definition of done" the agent re-checks every step** | *"Explore → Plan → Implement → Commit"*; a `/goal` condition where *"a separate evaluator re-checks after every turn"* ([best-practices](https://code.claude.com/docs/en/best-practices)) | **`/goal` mode**: *"the goal text acts as both the starting prompt and the completion criteria. Codex uses it to decide what to do next and whether the task is complete"* ([prompting](https://developers.openai.com/codex/prompting)) | **`phoenix-goal`** writes a frozen `done-check.json` (a real `command_exit`) *before any code*; the loop must satisfy it, never weaken it |
| **Decompose into small verifiable subtasks** | *"decomposes a task into a sequence of steps… programmatic checks ('gate') on any intermediate steps"* ([building-effective-agents](https://www.anthropic.com/engineering/building-effective-agents)) | *"break it into smaller, focused steps. Smaller tasks are easier for Codex to test and for you to review"* ([prompting](https://developers.openai.com/codex/prompting)) | **`phoenix-plan`** → `backlog.json`, **each item carrying its own objective `check`** |
| **Ground completion in objective signals, not self-judgment** | *"Give Claude a check it can run: tests, a build… the loop closes on its own"*; *"show evidence rather than asserting success"* ([best-practices](https://code.claude.com/docs/en/best-practices)) | *"Codex produces higher-quality outputs when it can verify its work… run linting and pre-commit checks"* ([prompting](https://developers.openai.com/codex/prompting)) | **`phoenix_sense` + the gate ledger** — completion is *derived from the trace* (`accept`: red→green, intact chain, green now), never self-reported |
| **Externalize state to the filesystem so a fresh context can resume** | *"Two mechanisms carry knowledge across sessions: CLAUDE.md files… Auto memory: notes Claude writes itself"* ([memory](https://code.claude.com/docs/en/memory)) | *"Put longer task specs and repo-local instructions in workspace files such as `repo/task.md` or `AGENTS.md`"* ([sandboxes](https://developers.openai.com/api/docs/guides/agents/sandboxes)) | **`.phoenix-ralph/`** on disk: `backlog.json`, `progress.md` (append-only memory), `done-check.json` — re-read every iteration |
| **Fresh context per iteration / context compaction** | *"the SDK automatically compacts the conversation… CLAUDE.md content is re-injected on every request"* ([agent-loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)) | *"With repeated compaction, Codex can continue working on complex tasks over many steps"* ([prompting](https://developers.openai.com/codex/prompting)) | **`phoenix-ralph` (mode B)** re-invokes `copilot -p` with a **fresh context every loop** (Huntley's trick against ~150k-token degradation) |
| **Dynamic orchestration when subtasks aren't predictable** | *"a central LLM dynamically breaks down tasks, delegates… and synthesizes their results… you can't predict the subtasks needed"* (orchestrator-workers, [building-effective-agents](https://www.anthropic.com/engineering/building-effective-agents)) | local `/plan` → cloud delegation; subagents to *"parallelize complex tasks"* ([workflows](https://developers.openai.com/codex/workflows)) | **`phoenix-auto`** senses state (green/red, stage, backlog) and picks the next skill at runtime, with oscillation + confidence guards |
| **Sandbox + bounded iteration** | *"extensive testing in sandboxed environments… stopping conditions (maximum iterations)"*; `maxTurns` / `maxBudgetUsd` ([building-effective-agents](https://www.anthropic.com/engineering/building-effective-agents)) | *"Codex creates a container… Agent internet access is off by default"* ([environments](https://developers.openai.com/codex/cloud/environments)) | The Ralph **driver owns budgets** (`-MaxLoops`, `-MaxMinutes`, `-NoProgressStop`) + a no-progress stop |
| **A persistent instruction/guidance file** | **CLAUDE.md** — *"re-injected on every request"*, survives compaction ([memory](https://code.claude.com/docs/en/memory)) | **AGENTS.md** — *"the agent uses it to find project-specific lint and test commands"* ([environments](https://developers.openai.com/codex/cloud/environments)) | Phoenix installs a **`phoenix.agent.md`** agent definition + the skill pack; **`PROMPT.md`** is the fixed per-loop instruction re-read every iteration |

**The one place Phoenix diverges — and why it matters for long horizons.** Every loop above still ends
in a *subjective* stop on its own: Anthropic's evaluator and OpenAI's goal-completion check are both an
LLM judging output; Codex hands you a diff to review. That's fine when a human is watching. Over a
multi-hour unattended run it's exactly where silent failures accumulate. Phoenix replaces the stop
signal with **`phoenix-mcp accept`**: done is true only if the *tamper-evident, hash-chained trace*
shows the acceptance check went **red → green** for the same check and is green now. A check never seen
failing is rejected (vacuous-gate guard); a dishonest edit breaks the chain. **Opinion at the finish
line becomes evidence** — which is the property you actually need before you walk away from a loop.

> Both labs give the agent a goal and a verifier and let it run. Phoenix adds the missing piece for
> *unattended* long-horizon work: a completion proof the agent cannot fake.

Full citations and the technique-by-technique source breakdown live in
[`../research/long-horizon-agent-design.md`](../research/long-horizon-agent-design.md).

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
