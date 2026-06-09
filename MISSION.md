# ATV-Phoenix — Mission

> _Rises from its own ashes. Senses when it's broken, heals itself, and gets better with use._

## One sentence
**ATV-Phoenix is a fast, Rust-based agentic harness that makes intent-to-outcome physical:
it carries portable skills (agentskills.io), senses and heals its own failures, and compounds
capability over time — frozen model, evolving scaffolding.**

## The thesis (grounded in our own ATV POV, last-10-days channel signal)
**The orchestration layer — not the model — determines agent success.** (All-The-Vibes/Agent-Harness
white paper; "the harness is the chassis, the model is the engine" — David Crawford; "if your code
fails, fix your harness not your code" — Mark Rowe.) Most failures blamed on the model are *harness*
failures: infinite loops (no explicit completion signal), context exhaustion (no summarization),
destructive actions (no policy gate), tool misuse (vague tool contracts), no self-correction (the
harness never feeds actionable errors back into the loop). Phoenix is a bet on the harness being the
thing worth building — fast, self-healing, and measured.

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
| 5 | **Context Lifecycle** | context window = finite depletable resource | **token-per-outcome** is a tracked metric; "make every token pay rent" |
| + | **Self-Healing** (Phoenix) | sensed failures trigger bounded, logged recovery | "fix your harness not your code" — heal the harness (context/tools/loop), then retry |
| + | **Self-Improvement** (Phoenix) | skills/prompts get better with use | measured gains on sealed evals (our criteria-first result), human-directed |

## Token efficiency is a first-class, MEASURED non-negotiable
The community pain is real and recent: *"Liam will burn 45k tokens when he shows up with 50 skills"*
(Andreas Wasita); *"make every token pay rent"* (Mark Rowe). agentskills.io progressive disclosure
helps (load names+descriptions at discovery, full instructions only on activation) — but at 50+ skills
even descriptions are expensive. **Phoenix's answer: a Rust-side skill index with lazy / retrieval-based
activation, so the model only ever sees skills relevant to the current intent.** We track
**tokens-per-verified-outcome** as a primary metric alongside verified-outcome rate. A harness that
wins the outcome but wastes the context budget is only half-built.

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
  (context, tool feedback, loop discipline) before the model or the task — "fix your harness not your code."
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
**A Rust harness that: (1) discovers + loads an agentskills.io skill from disk, (2) executes a
task through it, (3) SENSES success/failure from an objective signal, and (4) on failure performs
ONE bounded, logged self-heal (retry-or-rollback) — with every step written to an inspectable
trace.** Success = a runnable binary where an injected failure is *detected and recovered*, proven
by the trace, not by assertion. Everything else (RSI, compounding, multi-skill, integrations)
builds on top of that proven spine.

## What success looks like (the verifiable outcome, not vibes)
- v0: `cargo run` executes a skill, an injected fault is sensed, a heal fires, trace shows it. ✅/❌
- v1: skills self-improve against a sealed eval with a *measured* gain (reusing our eval-harness pattern).
- vN: Phoenix runs a real goal from the user's digital life end-to-end, with evidence at each stage.

## Grounding (researched 2026-06-09)
- Hermes Agent (NousResearch, local `code/hermes`): self-improving loop, autonomous skill creation,
  skills improve during use, agentskills.io-compatible.
- agentskills.io: open SKILL.md standard, progressive disclosure (Anthropic-originated, multi-vendor).
- Addy Osmani agent-skills: lifecycle commands + verification gates + anti-rationalization tables.
- ATV-StarterKit (All-The-Vibes): one-command Copilot agentic setup; pillars = Karpathy guardrails,
  Autoresearch, Compound Engineering, gstack, agent-browser; "repo gets smarter every session."
- This session's I2O result: criteria-first verification beats raw utterance where constraints matter.

_Frozen weights. Human owns direction. Gains proven on evidence, not self-grading. Never stop improving._
