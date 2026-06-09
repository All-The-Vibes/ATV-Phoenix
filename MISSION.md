# ATV-Phoenix — Mission

> _Rises from its own ashes. Senses when it's broken, heals itself, and gets better with use._

## One sentence
**ATV-Phoenix is a self-healing harness *for GitHub Copilot* — installed like ATV-StarterKit
(plugin marketplace + npx) — that carries portable agentskills.io skills, senses and heals failures
via a fast Rust MCP companion, and compounds capability over time. Built with Claude Code; runs on Copilot.**

## Target runtime: GitHub Copilot (this is a Copilot harness, not a standalone agent)
Phoenix does NOT ship its own model loop. **The agent runtime is GitHub Copilot** (CLI + VS Code).
Phoenix is the orchestration/skills/healing layer that installs INTO Copilot — exactly as
ATV-StarterKit does — using Copilot's real extension points:
| Copilot extension point | Phoenix uses it for |
|---|---|
| **`/skills`** (agentskills.io `SKILL.md`) | the portable capability library (discover→activate→execute) |
| **`/agent`** definitions | specialized personas/behavioral contracts |
| **instructions** (`copilot-instructions.md`, `AGENTS.md`, `.github/instructions/**`) | lean behavioral contracts / context engineering |
| **`/mcp`** servers | **the Rust spine** — a fast MCP companion exposing sense / heal / skill-index / trace tools |
| **`/plugin` marketplace** + npx installer | distribution: `copilot plugin marketplace add` + `npx atv-phoenix init` into `.github/`, `~/.copilot/` |

**Where Rust earns its place:** a single fast, inspectable **Rust MCP server** that Copilot connects to,
providing the capabilities Copilot can't do natively — objective **sensing**, bounded **self-healing**,
a token-cheap **skill index** (lazy/retrieval activation), and an append-only **trace** with per-step
token cost. The skills/agents/instructions stay portable markdown; the *spine* is Rust.

**Build vs. run (don't confuse them):** we BUILD Phoenix using **Claude Code CLI dynamic workflows**
(dev-time tool). The PRODUCT runs on **GitHub Copilot** (the thing users install). Claude Code never
ships to users.

## The thesis (grounded in our own ATV POV + today's channel signal)
**The orchestration layer — not the model — determines agent success.** (All-The-Vibes/Agent-Harness
white paper; "the harness is the chassis, the model is the engine" — David Crawford.) Most failures
blamed on the model are *harness* failures: infinite loops (no explicit completion signal), context
exhaustion (no summarization), destructive actions (no policy gate), tool misuse (vague tool contracts),
no self-correction (the harness never feeds actionable errors back into the loop). Phoenix is a bet on
the harness being the thing worth building — fast, self-healing, and measured.

## But Phoenix is an INTELLIGENT PLATFORM, not just a harness (your reframe, today)
Today in-channel you drew the line: *"that's just agent behaviour — now we're talking about an
**intelligent platform**."* That's the ambition. A harness orchestrates one agent's turn; an intelligent
platform **carries skills, senses its own health, heals, improves, and hosts an extensible ecosystem**
across many runs. Phoenix is the harness done so well it becomes a platform. (Stephanie Schofield in the
same thread anchored it to **Hermes**; Brandon Hurlburt rightly challenged "isn't this just Agency / a
GHCP plugin marketplace?" — so Phoenix must EARN its existence by doing what those don't: a *fast,
self-healing, self-improving, token-measured* core, and reuse — not reinvent — the skill/plugin standards.)

## Why this exists
Most agent harnesses are answer machines: you ask, they reply, and nobody checks whether the
*outcome* actually happened. The thing that separates a reliable agent from a chatbot is not a
bigger model — it is **persistence + closed-loop verification + compounding skills** around a
frozen model. We proved a piece of that thesis this session: forcing an agent to formalize
success criteria *before* acting measurably beats winging it, but only where satisfying and
checking constraints is the real work (the "criteria-first" result: raw 0.833 → 1.000 on a
constraint suite, 0 regressions, two independent runs). Phoenix is the engine that turns that
finding into a system you can actually run against your digital life.

## What "Hermes-like" means here (concrete, not vibes)
Phoenix borrows three behaviors from self-improving agents (Hermes / our own goose loop) and
makes them native, fast, and inspectable:
1. **Sensing** — it knows when a task failed, a skill regressed, or its own state is corrupt,
   from *objective signals* (exit codes, test results, schema/hash checks), not self-grading.
2. **Self-healing** — on a sensed failure it attempts a bounded, logged recovery (retry,
   rollback to last-good, repair, or escalate) instead of silently shipping a broken result.
3. **RSI at the scaffolding level (honest framing)** — it improves its **skills, prompts, and
   tactics** against sealed evals with *measured* gains; it does **not** retrain or rewrite its
   own model weights. The human sets direction; evidence — not the model's opinion — gates change.

## What "modern harness capability" means (the agent-skills layer)
- **agentskills.io-native:** a skill is a folder with a `SKILL.md` (metadata + instructions),
  optionally bundling scripts/references/assets. Phoenix loads skills by **progressive disclosure**
  (discover names/descriptions → activate full instructions on match → execute).
- **Lifecycle gates** (à la Addy's agent-skills / ATV's compound-engineering): spec → plan →
  build → **verify** → review → ship, with verification as a hard gate, not a suggestion.
- **Portable:** skills authored for Phoenix run on any agentskills.io-compatible client, and
  vice-versa. We adopt the standard; we don't fork it.

## Phoenix stands on the Five Pillars (ATV Agent-Harness POV) — and extends them
A production harness needs all five; remove one and it collapses inside the first multi-step task.
Phoenix implements them in Rust and adds the two things the POV repo's TS prompt-skeleton does NOT have:
**self-healing** and **measured self-improvement**.

| # | Pillar (ATV POV) | Guarantee | Phoenix's extension |
|---|---|---|---|
| 1 | **Context Assembly** | max comprehension per token | Rust skill INDEX + lazy/retrieval activation — only *relevant* skill descriptions enter context |
| 2 | **Tool Integrity** | every tool call schema-validated, actionable errors | validation errors are fed back as heal signals, not dead ends |
| 3 | **Loop Discipline** | explicit signals (not heuristics) to continue/retry/halt | the **Sensor** — objective signals (exit code/test/hash), never self-grading |
| 4 | **Policy Enforcement** | permission gate before any side effect | reversible-by-default; destructive acts require confirmation/are rollback-eligible |
| 5 | **Context Lifecycle** | context window = finite depletable resource | **tokens-per-verified-outcome** is a tracked metric |
| + | **Self-Healing** (Phoenix) | sensed failures trigger bounded, logged recovery | suspect the harness first (context/tools/loop), heal, then retry |
| + | **Self-Improvement** (Phoenix) | skills/prompts get better with use | measured gains on sealed evals (our criteria-first result), human-directed |

## Token efficiency is a first-class, MEASURED non-negotiable (with one honest caveat)
The community pain is real and recent: *"Liam will burn 45k tokens when he shows up with 50 skills"*
(Andreas Wasita). agentskills.io progressive disclosure helps (load names+descriptions at discovery,
full instructions only on activation) — but at 50+ skills even descriptions are expensive. **Phoenix's
answer: a Rust-side skill index with lazy / retrieval-based activation, so the model only ever sees
skills relevant to the current intent.** We track **tokens-per-verified-outcome** as a primary metric
alongside verified-outcome rate.
> **Honest caveat (Zach Luz, today):** *"Do token costs actually matter for us? I thought it's all
> unlimited."* For internal users on flat-rate plans, raw $ may not bite — but tokens are still a
> *latency* and *context-window* budget: fewer tokens = faster turns + more room for the actual task.
> So we keep token-efficiency as an engineering metric (speed/quality), not primarily a cost one.

## Positioning: a context-engineering harness, not a spec/persona generator
Your own channel question: *"isn't spec kit and persona based harnesses getting obsoleted for modern
AIs?"* The consensus is yes — *"specs next to featureset… personas → behavioral contracts… all in
favor of Context Engineering"* (Hassan Tariq); *"spec-driven burns more tokens for everyday use…
harness engineering burns way less and feels like riding the agents rather than vibing"* (Andreas
Wasita). Phoenix is deliberately on the **harness/context-engineering** side: lean behavioral
contracts + just-in-time context, NOT monolith spec docs or heavyweight personas. This is the
technical reason behind "disregard process ceremony" — ceremony burns tokens for no outcome gain.

## Non-negotiables (the architecture's spine)
- **The harness determines the outcome.** When something fails, suspect the harness first
  (context, tool feedback, loop discipline) before the model or the task.
- **Reuse standards, don't reinvent.** Phoenix must earn its existence vs Agency / GHCP plugin
  marketplace / Hermes — by being a faster, self-healing, self-improving, token-measured core that
  ADOPTS agentskills.io rather than forking the ecosystem.
- **Token efficiency is a measured guarantee,** not a nice-to-have. Track tokens-per-verified-outcome.
- **Evidence-first.** Every claimed outcome carries objective evidence (exit code, test pass,
  schema/hash check, artifact). "Unknown" is allowed; fabricated success is a severe failure.
- **Frozen model + evolving scaffolding.** No weight training. Improvement is skills/prompts/
  tactics, gated by measured gains on sealed evals.
- **Human owns direction.** The loop executes and verifies; choosing *what* to pursue stays human.
- **Fast and inspectable.** Rust core; every decision, heal, and skill-load is logged and replayable.
- **Reversible by default.** Self-healing prefers rollback-to-last-good over irreversible action.

## How we build (explicitly disregarding process ceremony)
No PMI ritual, no Gantt theater, no story-point liturgy. Instead:
- **Smallest verifiable slice first.** v0 does ONE real thing end-to-end and proves the spine,
  before any breadth. If a slice can't be objectively verified, it isn't done.
- **Evidence over process.** A passing check beats a status update. We measure; we don't narrate.
- **Document what worked AND what didn't.** `BUILDLOG.md` is a running, honest engineering log —
  dead ends, wrong turns, and reversals included. Failure that's recorded is progress; failure
  that's hidden is debt.
- **Steal shamelessly, fork reluctantly.** Reuse agentskills.io, Hermes patterns, ATV pillars.
  Build new only where the Rust speed/sensing/healing spine genuinely needs it.

## The first verifiable slice (v0 — defined so this can't become architecture astronomy)
**A Rust MCP server that GitHub Copilot connects to via `/mcp`, exposing three tools — `sense`
(check an objective signal: exit code / test / file-or-hash), `heal` (one bounded, logged recovery:
retry-or-rollback), and `trace` (append-only JSONL with per-step token cost) — proven by a real
Copilot session where an injected fault is SENSED and a heal FIRES, shown in the trace.** The skill it
operates on is a single agentskills.io `SKILL.md`. Success = inside an actual Copilot run, the fault
is *detected and recovered*, evidenced by the trace, not by assertion. Everything else (skill-index
retrieval, RSI/compounding, multi-skill, agents, npx installer, marketplace) builds on this proven spine.

## What success looks like (the verifiable outcome, not vibes)
- v0: Copilot loads the Phoenix MCP server; a skill runs; an injected fault is sensed; a heal fires;
  the trace (with token cost) proves it. ✅/❌
- v1: skills self-improve against a sealed eval with a *measured* gain (reusing our eval-harness pattern).
- v2: one-command install (`copilot plugin marketplace add` / `npx atv-phoenix init`) lands the full
  Phoenix harness (skills + agents + instructions + MCP server) into a repo, ATV-StarterKit-style.
- vN: Phoenix runs a real goal from the user's digital life end-to-end on Copilot, evidence at each stage.

## Grounding (researched 2026-06-09)
- Hermes Agent (NousResearch, local `code/hermes`): self-improving loop, autonomous skill creation,
  skills improve during use, agentskills.io-compatible.
- agentskills.io: open SKILL.md standard, progressive disclosure (Anthropic-originated, multi-vendor).
- Addy Osmani agent-skills: lifecycle commands + verification gates + anti-rationalization tables.
- ATV-StarterKit (All-The-Vibes): one-command Copilot agentic setup; pillars = Karpathy guardrails,
  Autoresearch, Compound Engineering, gstack, agent-browser; "repo gets smarter every session."
- This session's I2O result: criteria-first verification beats raw utterance where constraints matter.

_Frozen weights. Human owns direction. Gains proven on evidence, not self-grading. Never stop improving._
