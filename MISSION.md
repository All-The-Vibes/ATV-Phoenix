# ATV-Phoenix — Mission

> _Rises from its own ashes. Senses when it's broken, heals itself, and gets better with use._

> **Status note (updated 2026-06-10).** This is the original **founding charter** — the vision and POV
> Phoenix was built against. For what has actually shipped, see [`README.md`](README.md) and
> [`CHANGELOG.md`](CHANGELOG.md). Two things below describe the *intended* future, not today's reality:
> the **install path** is `setup.py` today (the `copilot plugin marketplace` / `npx` distribution is
> still scaffolded), and Phoenix ships its **own 13 ground-up skills** (all original, written from
> scratch — no third-party skill packs).

## One sentence
**ATV-Phoenix is a self-healing harness *for GitHub Copilot* (and Microsoft Scout) — installed today via
a one-command `setup.py` (a `plugin marketplace` + `npx` path is planned) — that carries a bundled pack
of agentskills.io skills, senses and heals failures via a fast Rust MCP companion, and compounds
capability over time. Built with Claude Code; runs on Copilot.**

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
white paper; "the harness is the chassis, the model is the engine" — a community member.) Most failures
blamed on the model are *harness* failures: infinite loops (no explicit completion signal), context
exhaustion (no summarization), destructive actions (no policy gate), tool misuse (vague tool contracts),
no self-correction (the harness never feeds actionable errors back into the loop). Phoenix is a bet on
the harness being the thing worth building — fast, self-healing, and measured.

## But Phoenix is an INTELLIGENT PLATFORM, not just a harness (your reframe, today)
Today in-channel you drew the line: *"that's just agent behaviour — now we're talking about an
**intelligent platform**."* That's the ambition. A harness orchestrates one agent's turn; an intelligent
platform **carries skills, senses its own health, heals, improves, and hosts an extensible ecosystem**
across many runs. Phoenix is the harness done so well it becomes a platform. (a community member in the
same thread anchored it to **Hermes**; a community member rightly challenged "isn't this just Agency / a
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
- **Lifecycle gates** (verification-first compound engineering): think → plan →
  build → test → debug → context → **review** → ship, with verification as a hard gate, not a suggestion.
- **Portable:** skills authored for Phoenix run on any agentskills.io-compatible client, and
  vice-versa. We adopt the standard; we don't fork it.
- **Built ground-up:** Phoenix ships its **own 13-skill pack**, written from scratch in the `SKILL.md`
  standard — proven structural devices (ASCII decision diagrams, *Common Rationalizations* tables,
  *Red Flags*) but with **every gate an objective `phoenix_sense` check**, fast, self-healing, and
  token-efficient, folding in craft from Karpathy, Mat Pocock, and Emil Kowalski. We build new for the
  spine and the verification-gated lifecycle, and compose proven companions (TokenMasterX) rather than
  fork them. Every skill is original.

## Token-efficient retrieval = ADOPT TokenMasterX (already built + measured by you)
We do NOT build this from scratch — **you already built and measured it: `shyamsridhar123/TokenMasterX`.**
It is a routing agent for **the exact same hosts** (Claude Code + GitHub Copilot CLI), distributed the
**exact same way** Phoenix will be (plugin marketplace + a per-repo `/token-master` command), backed by
**graphify** (default, no-LLM structural index) with **codegraph** (AST) as a precise escalation. Its thesis
is Phoenix's Context Assembly pillar verbatim: *the model pays once to understand structure, then never again
— structural questions ("who calls X", "what breaks if I change Y") route to a prebuilt code graph instead of
grep-re-reading the transcript every turn.*
- **Measured (don't re-derive):** −73% cumulative input tokens, 3.71× more efficient, up to **7.8× on
  blast-radius**, 12/12 tasks answered from the graph, **zero correctness regressions** — 36 live Copilot
  runs across scikit-learn + sympy; honest negative reported (−44% on one sympy inheritor case).
- **Key design lesson it already proved:** *offering* the graph isn't enough (model used it 0/15 times
  unprompted) — you must **enforce** routing (8/8 when nudged). Phoenix inherits "enforce, don't offer."
- **Phoenix's move: COMPOSE, not rebuild.** TokenMasterX IS Phoenix's Context Assembly + skill/code-graph
  retrieval layer. Phoenix adds the other pillars (sense / heal / trace / lifecycle skills / agents) around it.
- **Why this is huge for credibility:** TokenMasterX is effectively a **proven single-pillar prototype of the
  Phoenix architecture** — same hosts, same install path, same MCP+routing-agent mechanism. One pillar already
  ships and works with hard numbers, which de-risks the whole platform thesis.

## Phoenix stands on the Five Pillars (ATV Agent-Harness POV) — and extends them
A production harness needs all five; remove one and it collapses inside the first multi-step task.
Phoenix implements them in Rust and adds the two things the POV repo's TS prompt-skeleton does NOT have:
**self-healing** and **measured self-improvement**.

| # | Pillar (ATV POV) | Guarantee | Phoenix's extension |
|---|---|---|---|
| 1 | **Context Assembly** | max comprehension per token | **adopt TokenMasterX** — graph-routed structural retrieval (graphify+codegraph), proven −73% tokens; only the relevant subgraph enters context |
| 2 | **Tool Integrity** | every tool call schema-validated, actionable errors | validation errors are fed back as heal signals, not dead ends |
| 3 | **Loop Discipline** | explicit signals (not heuristics) to continue/retry/halt | the **Sensor** — objective signals (exit code/test/hash), never self-grading |
| 4 | **Policy Enforcement** | permission gate before any side effect | reversible-by-default; destructive acts require confirmation/are rollback-eligible |
| 5 | **Context Lifecycle** | context window = finite depletable resource | **tokens-per-verified-outcome** is a tracked metric |
| + | **Self-Healing** (Phoenix) | sensed failures trigger bounded, logged recovery | suspect the harness first (context/tools/loop), heal, then retry |
| + | **Self-Improvement** (Phoenix) | skills/prompts get better with use | measured gains on sealed evals (our criteria-first result), human-directed |

## Token efficiency is a first-class, MEASURED non-negotiable (with one honest caveat)
The community pain is real and recent: *"a user will burn 45k tokens when he shows up with 50 skills"*
(a community member). agentskills.io progressive disclosure helps (load names+descriptions at discovery,
full instructions only on activation) — but at 50+ skills even descriptions are expensive. **Phoenix's
answer: a Rust-side skill index with lazy / retrieval-based activation, so the model only ever sees
skills relevant to the current intent.** We track **tokens-per-verified-outcome** as a primary metric
alongside verified-outcome rate.
> **Honest caveat (a community member, today):** *"Do token costs actually matter for us? I thought it's all
> unlimited."* For internal users on flat-rate plans, raw $ may not bite — but tokens are still a
> *latency* and *context-window* budget: fewer tokens = faster turns + more room for the actual task.
> So we keep token-efficiency as an engineering metric (speed/quality), not primarily a cost one.

## Positioning: a context-engineering harness, not a spec/persona generator
Your own channel question: *"isn't spec kit and persona based harnesses getting obsoleted for modern
AIs?"* The consensus is yes — *"specs next to featureset… personas → behavioral contracts… all in
favor of Context Engineering"* (a community member); *"spec-driven burns more tokens for everyday use…
harness engineering burns way less and feels like riding the agents rather than vibing"* (a community member
a community member). Phoenix is deliberately on the **harness/context-engineering** side: lean behavioral
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
- **Steal shamelessly, fork reluctantly — COMPOSE proven parts.** Phoenix *assembles* what already
  works (**TokenMasterX** — the measured token/retrieval layer, agentskills.io patterns, Hermes
  patterns, ATV pillars) and **builds new for everything that defines it: the 13-skill
  verification-gated pack and the genuinely-novel spine — objective sensing, bounded self-healing, and
  measured self-improvement.** If a capability already ships and is measured (TokenMasterX), we adopt
  it; the skills and spine are original.

## The first verifiable slice (v0 — defined so this can't become architecture astronomy)
**A Rust MCP server that GitHub Copilot connects to via `/mcp`, exposing four tools — `sense`
(check an objective signal: exit code / test / file-or-hash), `snapshot` (bless a known-good state only
if a check passes), `heal` (one bounded, logged recovery: retry-or-rollback), and `verify_trace`
(audit the append-only hash-chained JSONL) — proven by a real Copilot session where an injected fault
is SENSED and a heal FIRES, shown in the trace.**The skill it
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
- **TokenMasterX (shyamsridhar123/TokenMasterX — YOUR repo):** routing agent for Claude Code + Copilot
  CLI; graph-routed structural retrieval (graphify default + codegraph AST escalation); measured −73%
  cumulative input tokens / 3.71× / up to 7.8× blast-radius / 0 regressions over 36 live Copilot runs;
  same plugin-marketplace install path Phoenix uses. **Adopt as Phoenix's Context Assembly pillar.**
- Hermes Agent (NousResearch, local `code/hermes`): self-improving loop, autonomous skill creation,
  skills improve during use, agentskills.io-compatible.
- agentskills.io: open SKILL.md standard, progressive disclosure (Anthropic-originated, multi-vendor).
- graphify (installed `~/.local/bin/graphify`): any input → knowledge graph; the extraction engine for
  Phoenix's skill-graph + code-graph token-efficient retrieval.
- ATV-StarterKit (All-The-Vibes): one-command Copilot agentic setup; pillars = Karpathy guardrails,
  Autoresearch, Compound Engineering, gstack, agent-browser; "repo gets smarter every session."
- This session's I2O result: criteria-first verification beats raw utterance where constraints matter.

_Frozen weights. Human owns direction. Gains proven on evidence, not self-grading. Never stop improving._
