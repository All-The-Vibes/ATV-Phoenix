# The developer journey — greenfield, end to end

How everything in Phoenix comes together on a real build. This walks a **greenfield** project from a
one-line idea to a *proven* shipped outcome, naming each skill and component at the moment it fires.

If you only remember one thing: **every phase ends in an objective `phoenix_sense` gate, and the
autonomous engine ([`phoenix-ralph`](../skills/phoenix-ralph/SKILL.md)) only stops when the trace
*proves* the work is done — never when the model says so.**

---

## 0. One-time setup

```powershell
git clone https://github.com/All-The-Vibes/ATV-Phoenix
cd ATV-Phoenix
python .copilot-plugin/skills/phoenix-setup/setup.py --repo .
```

`setup.py` builds the Rust spine (`phoenix-mcp`), registers the `phoenix` MCP server, and installs the
**16-skill pack** + **TokenMasterX** (graph navigation). After that, skills **auto-activate by their
descriptions** — you describe work in plain language and the right skill engages. `phoenix-mcp doctor`
validates every bundled skill against the spine.

---

## The substrate (constant under every phase)

Everything below rides on the **5 spine tools + a tamper-evident trace**:

| Tool | Role |
|---|---|
| `phoenix_sense(check)` | objective pass/fail — a command's exit code, a file hash, or a regex. No self-grading. |
| `phoenix_snapshot(path, check)` | save a known-good state — *only if* the check passes. |
| `phoenix_heal(strategy, ctx)` | bounded recovery (rollback / retry ≤3), confirmed by an external recheck. |
| `phoenix_verify_trace()` | audit the hash-chained log of everything sensed and healed. |
| `phoenix_accept(check)` | **the gate ledger** — ok only if the trace proves the check went **red → green** and is green now. |

And the **6 Phoenix Laws** apply across every skill: verify-never-assume · snapshot-before-risk ·
bounded-effort (≤3, then stop) · surface-assumptions · token-discipline (ask the graph, not grep) ·
evidence-over-self-grading.

---

## The journey: *"Build me a link-shortener service in TypeScript"*

```
   You: a one-line, slightly-vague goal
        │
   [phoenix]  ── the router reads the task and dispatches ──┐
        │                                                   │
        │  Known path? → fixed lifecycle (1–6 below)        │
        │  Hands-off "go build it"? → autonomous engine ────┘ (see "Autonomous mode")
        ▼
 ┌─ 1. THINK ─ phoenix-think ───────────────────────────────────────────────┐
 │ Socratic interview + evidence-grounded research. Surfaces ASSUMPTIONS out │
 │ loud (auth? custom slugs? persistence? rate limits?). Deliverable is NOT  │
 │ prose — it's a crystal intent + a *runnable acceptance check*.            │
 └──────────────────────────────────────────────────────────────────────────┘
        │   (fuzzy goal / want it driven to completion? → phoenix-goal:
        │    it FORMALIZES the objective done-check, then decomposes)
        ▼
 ┌─ 2. PLAN ─ phoenix-plan ─────────────────────────────────────────────────┐
 │ Decompose intent into small, individually-verifiable steps, ordered so    │
 │ the build stays GREEN between them. Each step carries its own check.       │
 └──────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─ 3. BUILD ↔ TEST/DEBUG ─ the inner loop, once per step ──────────────────┐
 │ phoenix-build : snapshot → smallest edit → sense → heal-if-red.           │
 │   ├─ phoenix-test       : write the FAILING test first (red), then code   │
 │   │                       to green — the test IS the gate.                 │
 │   ├─ phoenix-typescript : `tsc --noEmit` IS the gate — strict, no `any`.  │
 │   ├─ phoenix-craft      : Karpathy guardrails — simple, surgical changes. │
 │   ├─ phoenix-design     : any UI → animation-decision framework +         │
 │   │                       Before/After, gated by build/lint.              │
 │   ├─ phoenix-context    : "what calls createSlug?" routes to the          │
 │   │                       TokenMasterX code GRAPH, not grep (−73% tokens).│
 │   └─ phoenix-debug      : a check went red → reproduce, isolate via the   │
 │                           graph, fix the ROOT, confirm green.             │
 │ (phoenix-self-heal is this loop's reusable core.)                         │
 └──────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─ 4. REVIEW ─ phoenix-review ─────────────────────────────────────────────┐
 │ Re-run EVERY check against the Intent Contract. Confirm 0 regressions.    │
 │ Inspect the tamper-evident trace.                                         │
 └──────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─ 5. SHIP ─ phoenix-ship ─────────────────────────────────────────────────┐
 │ Final sense + phoenix_accept. Reports done ONLY on green evidence, with   │
 │ the trace as proof.                                                       │
 └──────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─ 6. LEARN ─ phoenix-okf ─────────────────────────────────────────────────┐
 │ Produce an OKF bundle from the code graph: browsable, git-diffable,       │
 │ sense-gated knowledge. Next session, phoenix-context re-consumes it       │
 │ index-first as cheap context — the project starts smarter.                │
 └──────────────────────────────────────────────────────────────────────────┘
```

A task usually flows **think → plan → build (↔ test/debug) → review → ship → learn**, but you can
*enter at whatever phase matches reality* — a red check pulls `debug`, building a UI pulls `design`,
and so on. The skills activate themselves.

---

## Autonomous mode — built for long-horizon tasks

The lifecycle above assumes you're driving. For **long-running, multi-hour, many-step** greenfield work
("go build the whole thing, don't stop until it works"), the router hands off to Phoenix's autonomous
system — **`phoenix-goal` + `phoenix-ralph` + `phoenix-auto`** — which *reuses the same lifecycle skills
underneath*. This is the same shape both major labs converge on for long-horizon reliability — OpenAI
Codex ships a **`/goal` mode** (*"the goal text acts as both the starting prompt and the completion
criteria"*) and Anthropic recommends a **goal condition that a separate evaluator re-checks every turn**
— and Phoenix's contribution is making the completion signal a **tamper-evident proof** instead of a
judgment.

The three skills are one pipeline:

```
phoenix-auto  (dynamic router: senses state, picks the next skill at runtime)
    ├── vague goal ─────────▶ phoenix-goal  (FORMALIZE a persistent done-check + DECOMPOSE a backlog)
    │                              └── hands off to ▶ phoenix-ralph
    └── have a backlog ─────▶ phoenix-ralph (the persistence engine)
                                   └── drives ▶ phoenix-build / phoenix-test / phoenix-debug
                                   └── completion proven by ▶ phoenix-mcp accept (gate ledger)
```

- **[`phoenix-goal`](../skills/phoenix-goal/SKILL.md)** — the on-ramp. Turns one fuzzy goal into a
  *persistent definition of done* (`done-check.json`, a real `command_exit`) written **before any code**,
  then decomposes it into a backlog where each item carries its own objective check. The goal is the
  agent's north star for the whole run — the equivalent of Codex's `/goal`, but the criterion is a
  runnable check that must start **red**.
- **[`phoenix-ralph`](../skills/phoenix-ralph/SKILL.md)** — the engine. It wraps Geoffrey Huntley's Ralph
  loop — *fresh context every iteration, the filesystem as memory, one task per loop* — so a multi-hour
  job survives context-window degradation (the same fresh-context / compaction discipline Anthropic and
  Codex both use for long tasks). It adds the one thing every other autonomous loop lacks: an
  **objective, tamper-evident completion proof.**
- **[`phoenix-auto`](../skills/phoenix-auto/SKILL.md)** — the dynamic router. When the next step depends
  on results (Anthropic's orchestrator-workers case: *"you can't predict the subtasks needed"*), it
  senses current state (green/red, stage, backlog left?) and picks the next skill at runtime, with
  oscillation + confidence guards.

> Every other autonomous loop ends in an opinion — a human watching the stream, or an LLM approving an
> LLM. **Phoenix ends in evidence.**

The Ralph loop (mode B — unattended):

```
 driver: accept(done-check)?  ── proven green ──▶  DONE  (writes completed.json + git tag)
        │ not yet
        ▼
 copilot -p PROMPT.md      (FRESH context; agent reads backlog.json + progress.md, does ONE item)
        │
 verify-trace intact?      ── broken ──▶ STOP (tamper)
        │ ok
 state changed?            ── no, N× ──▶ STOP (stuck = a planning problem, not a grinding one)
        └──────────────────── loop ◀────────────
```

**The brain on disk (`.phoenix-ralph/`):** `backlog.json` (each item an *objective check*, not a prose
bullet), `progress.md` (append-only memory that survives the amnesiac context resets), `done-check.json`
(the top-level acceptance check), `completed.json` (the proof bundle).

**The crucial design choice: the driver — not the agent — owns "done."** The agent only *proposes*
state changes (edits files, sets `done:true`); the **driver derives completion from the trace**. An
agent that lies in `backlog.json` changes nothing, and dishonest edits break the hash chain.

Two ways to run it:
- **Interactive** — `/phoenix-ralph` in a live Copilot session; the agent's own tool-use loop *is* the
  loop, and it can't declare done until the `phoenix_accept` MCP tool returns ok.
- **Unattended** — [`dist/ralph/phoenix-ralph.ps1`](../dist/ralph/phoenix-ralph.ps1) re-invokes the
  agent with fresh context every loop for overnight / CI jobs, calling `phoenix-mcp accept`.

Full detail, the gate-ledger semantics, and the technique-by-technique alignment with Anthropic and
OpenAI Codex (with citations): [`autonomous-workflows.md`](autonomous-workflows.md) and
[`../research/long-horizon-agent-design.md`](../research/long-horizon-agent-design.md).

---

## How it all comes together (one paragraph)

The **router** picks the phase → each **lifecycle skill** does its job and **ends in a `phoenix_sense`
gate** → the **craft skills** (`craft` / `typescript` / `design`) raise quality inside `build`, while
**`phoenix-context` + TokenMasterX** keep it token-cheap → red checks pull **`debug` / `self-heal`** →
**`review` / `ship`** prove zero regressions through the **gate ledger** → **`phoenix-okf`** banks the
knowledge so the *next* greenfield run starts smarter. For hands-off work, **`phoenix-ralph`** runs that
entire lifecycle to completion unattended, stopping only on a trace-proven outcome. The Rust spine, the
5 tools, and the tamper-evident trace are the rails all of it runs on.

---

## The honest limits

- Recovery is **bounded objective recovery** (rollback / ≤3 retries), not general self-healing.
- The Ralph driver enforces **budgets** (`-MaxLoops`, `-MaxMinutes`, `-NoProgressStop`), not a hard
  sandbox.
- `phoenix_accept` proves *a check* went red→green — it's only as meaningful as the check. The
  failure-first + `command_exit` guards reject vacuous gates, but **garbage check in, garbage proof
  out**; check quality stays human-owned.
- Automatic distillation of each run's learnings into OKF isn't wired yet (that's hypothesis **H5**,
  open) — today you produce/author the bundle and it's re-consumed.

See [`../BUILDLOG.md`](../BUILDLOG.md) for the full honest engineering record, and [`../evals/`](../evals/)
for the data behind every claim.
