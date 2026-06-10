# ATV-Phoenix

![ATV-Phoenix](assets/hero.jpg)

**A self-healing harness for AI coding agents.** Phoenix gives GitHub Copilot (and Microsoft Scout)
the one organ they're missing: the ability to **objectively sense when a task actually failed, and
heal it** — instead of declaring "done" on silently-broken work.

> _Rises from its own ashes. Senses when it's broken, heals itself, gets better with use._

---

## The results that justify it

Three hypotheses, all tested on **live GitHub Copilot sessions**, scored by hidden checkers (ground truth):

| Question | Result |
|---|---|
| **Does objective verification beat self-judgment?** (H2) | Silent-failure rate **40% → 0%** across 20 sessions — vanilla Copilot shipped broken code with false confidence on tasks with hidden acceptance criteria; Phoenix caught and healed every one. **Zero regressions.** |
| **Does formalizing intent into a check first help?** (H1) | **+0.125** mean verified-outcome lift, **replicated 3/3 runs** (criteria-first perfect every run). |
| **Does injecting the right context/memory help?** (H3) | **0% → 100%** — without a project's convention, Copilot produced a plausible-but-wrong default every time; with it injected, correct every time. |
| **Does it hold up on a SWE-bench-style contract?** | Underspecified resolved-rate **50% → 100%** (overall **78% → 100%**, **0 regressions**) — both vanilla misses were *silent failures* the enforced test-gate caught. |

Together: **formalize intent + verify objectively + supply the right context.** And it isn't just
fault-recovery on broken files — under the loop, live Copilot **built a real project end-to-end**
(a working Space Invaders game) gated by an objective check + a hardened Playwright interaction gate.
Full method + raw data per experiment under [`evals/`](evals/).

---

## What Phoenix gives the agent (4 tools)

![The self-heal loop](assets/loop.jpg)

| Tool | What it does |
|---|---|
| `phoenix_sense` | Objectively check success — a command's exit code, a file hash, or a regex. **No self-grading.** |
| `phoenix_snapshot` | Save a known-good state — but **only if a check passes** (never blesses broken state). |
| `phoenix_heal` | Bounded recovery (rollback to a snapshot, or retry ≤3×), **confirmed by an external recheck**. |
| `phoenix_verify_trace` | Audit a tamper-evident, hash-chained trace of everything sensed and healed. |

The loop: **baseline-green → snapshot → edit → sense → heal if red → confirm green** — all on
*objective* signals, all traced.

---

## Install

### GitHub Copilot CLI (recommended)
```powershell
git clone https://github.com/All-The-Vibes/ATV-Phoenix
cd ATV-Phoenix
python .copilot-plugin/skills/phoenix-setup/setup.py --repo .
```
The setup script is idempotent: it builds the Rust binary if needed, registers the `phoenix` MCP
server in `~/.copilot/mcp-config.json`, and installs the `phoenix` agent. Restart Copilot, then ask it
to verify + heal a task — it calls the tools automatically. (Requires [Rust](https://rustup.rs) +
Python. `dist/install.ps1` is a PowerShell equivalent.)

### Microsoft Scout (CLI adapter)
Scout doesn't take external MCP servers, so Phoenix ships a **CLI** the Scout agent calls via its
shell tool, plus a Scout skill that teaches the verify-heal loop:
```powershell
phoenix-mcp sense   '{"kind":"command_exit","target":["pytest","-q"],"expect":0}'   # exit 0 = pass
phoenix-mcp snapshot src/app.py '{"kind":"command_exit","target":["pytest","-q"]}'
phoenix-mcp heal    rollback '{"path":"src/app.py","snap_id":"...","recheck":{...}}'
phoenix-mcp verify-trace
```
See [`dist/scout/`](dist/scout/). Same Rust binary, both hosts.

---

## Why it works (the thesis)

**The orchestration layer — not the model — determines agent success.** Most "the model failed"
problems are *harness* failures: no objective completion signal, no recovery, no evidence. Phoenix is
the missing layer. Two design principles it proves:

- **Enforce, don't offer.** In the experiment, unprompted Copilot self-verified **0/10** times. Value
  comes from the harness *enforcing* the verify-heal loop, not from a tool merely being available.
- **Evidence over self-grading.** `phoenix_sense` only reports objective signals; "I'm not sure it
  passed" is allowed, a fabricated "done!" is the failure mode Phoenix exists to prevent.

Phoenix builds only the novel spine — **objective sensing, bounded healing, measured improvement** —
and composes with proven companions rather than reinventing them (see the stack below).

---

## Intent-to-Outcome: this harness is the radio before the TV

![Radio before the TV](assets/radio-tv.jpg)

Phoenix isn't the destination — it's the **first working organ** of a larger system: an
**Intent-to-Outcome (I2O)** loop whose purpose is to reliably turn a human's *intent* into a
*verified outcome* across all of digital life — work, career, learning, and project delivery.

The I2O machine is a 7-stage loop — **SENSE → MODEL → FORMALIZE → PLAN/ACT → VERIFY → REFLECT →
DISTILL.** Phoenix productizes the three hardest middle stages — **FORMALIZE an intent into an
objective check, ACT, and VERIFY against that check (then heal)** — for one narrow domain: coding
agents, where the grader can be perfectly objective because code either runs or it doesn't.

**That narrowness is the strategy, not a limitation.** Radio proved the core primitive — broadcast a
signal over the air, a receiver reconstructs it — before television inherited that exact
infrastructure and added the picture. **Phoenix is the radio.** It proves, on live Copilot sessions
with hidden graders, that a *frozen* model plus a thin enforcement harness converts "looks done" into
"is done" (silent failures **40%→0%**, underspecified resolved-rate **50%→100%**). **The full I2O
system is the television** — the same closed-loop verification, generalized across the four pillars,
running *proactively* and *persistently*: sensing your Teams / mail / calendar, proposing Intent
Contracts, executing and verifying them, and compounding what it learns. Same signal, same loop,
bigger screen.

What carries over unchanged from the radio to the TV:

| Principle | In Phoenix today | In the full I2O system |
|---|---|---|
| **The Intent Contract** (`intent → verifiable success_criteria → evidence → outcome → delta`) | a `phoenix_sense` check *is* the success-criteria + evidence made executable | proposed automatically from sensed context, promoted by a human |
| **Evidence over self-grading** | `phoenix_sense` reports only objective signals; a fabricated "done!" is the failure mode it exists to kill | the non-negotiable that keeps a *proactive* system trustworthy |
| **Enforce, don't offer** | value comes from the loop being *run*, not merely available (unprompted self-verify: 0/10) | the heartbeat runs SENSE→FORMALIZE→VERIFY without being asked |
| **Frozen weights, human direction** | improvement is scaffolding-level (skills, checks, memory), evidence-gated | the human still sets goals; the system compounds the means |

The experiments in this repo — H1 (intent-fidelity), H2 (verifier-pass), H3 (memory-lift), and the
SWE-bench-style benchmark — *are* the early I2O hypotheses, tested first in the one domain with a
perfect grader. They're the radio broadcasts that prove the signal before the picture arrives — read
the full loop, the Intent Contract, and the H1–H6 backlog in **[`docs/intent-to-outcome.md`](docs/intent-to-outcome.md)**,
and see [`evals/`](evals/) for the raw data behind each.

## The recommended stack (Phoenix composes, it doesn't reinvent)

Phoenix is standards-native ([agentskills.io](https://agentskills.io) skills + MCP), so it stacks with
best-in-class companion plugins. `setup.py` detects what's installed and prints the install commands for
the rest.

| Layer | Component | Ships with Phoenix? |
|---|---|---|
| **Self-heal + full lifecycle + craft** (the core) | A comprehensive 13-skill pack: `phoenix` (router) + lifecycle (`think/plan/build/test/debug/context/review/ship`) + craft from the masters (`phoenix-craft` · Karpathy, `phoenix-typescript` · Mat Pocock, `phoenix-design` · Emil Kowalski) + `phoenix-self-heal` — every stage gated by an objective `phoenix_sense` check | **Bundled** (`skills/`, installed automatically) |
| **Token-efficient retrieval** | [TokenMasterX](https://github.com/shyamsridhar123/TokenMasterX) — graph-routed code navigation (−73% tokens) | **Bundled** (`vendor/token-master`, installed automatically; needs `graphify`) |
| **Extra lifecycle skills** | [Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills) — MIT general workflow pack | Optional companion (`agent-skills@addy-agent-skills`) |

`setup.py` installs the whole stack in one command: the **13-skill verification-gated pack** — a
meta-router, the full lifecycle (think → plan → build → test → debug → context → review → ship), and
craft skills distilling three masters' philosophies into objective gates (**Karpathy** code guardrails,
**Mat Pocock**'s TypeScript where `tsc --noEmit` is the gate, **Emil Kowalski**'s design-engineering with
its animation framework + Before/After review table) — plus the self-heal MCP server and the **bundled
TokenMasterX** (vendored MIT, `graphify`-backed). Every stage gates on an objective `phoenix_sense` check,
every skill carries a *Common Rationalizations* table and *Red Flags* section, and the pack is
**token-efficient by design** (structural questions route to the code graph; detail loads only on
activation). It is **self-maintaining**: `phoenix-mcp doctor` validates every bundled skill with Phoenix's
own spine, and `cargo test` fails if any skill drifts — the harness verifies itself.

---

## Status (v0.2.0)

Every milestone has a measured eval + a screenshot.

| Milestone | Proven | Evidence |
|---|---|---|
| M0 | token/retrieval pillar (TokenMasterX/graphify) validated | [result](evals/m0-install-path/RESULT.md) · [shot](evals/screenshots/m0-graph-viz.png) |
| M1 | self-healing spine in Rust (`cargo test`) | [result](evals/m1-self-heal/RESULT.md) · [shot](evals/screenshots/m1-self-heal.png) |
| M2 | works over real MCP protocol | [result](evals/m2-mcp/RESULT.md) · [shot](evals/screenshots/m2-mcp-session.png) |
| M3 | heals a fault **live inside Copilot** | [result](evals/m3-live-copilot/RESULT.md) · [shot](evals/screenshots/m3-live-copilot.png) |
| E2E | builds a **real project end-to-end** live in Copilot — Space Invaders, gated by an objective check + a **hardened Playwright interaction gate** (renders, animates, responds to keys) | [result](evals/e2e-sandbox/RESULT.md) · [shot](evals/screenshots/e2e-space-invaders.png) |
| H1 | criteria-first lift +0.125, replicated 3/3 | (goose I2O scorecard) |
| H2 | silent failures **40%→0%** | [result](evals/h2-experiment/RESULT.md) · [shot](evals/screenshots/h2-results.png) |
| H3 | context/memory lift **0%→100%** | [result](evals/h3-experiment/RESULT.md) · [shot](evals/screenshots/h3-results.png) |
| SWE-bench-lite | resolved-rate, underspecified tier **50%→100%** (overall 78%→100%, **0 regressions**) | [result](evals/swe-bench-lite/RESULT.md) · [shot](evals/screenshots/swe-bench-result.png) |

**Honest limits:** results are directional (small n, single model, deterministic checkers). Recovery is
"bounded objective recovery," not broad self-healing. Command timeouts aren't yet enforced in-process.
`copilot plugin install <repo>` (marketplace path) is scaffolded but not yet verified end-to-end —
install via `setup.py` today. See [`BUILDLOG.md`](BUILDLOG.md) for the full honest engineering record —
every bug, reversal, and dead end (including a dogfooding fix that cut a real run from 72 credits to 15).

## License
MIT — see [LICENSE](LICENSE). Phoenix bundles its **13-skill verification-gated pack** (MIT) and
**vendors TokenMasterX** (MIT © 2026 Shyam Sridhar) under [`vendor/token-master`](vendor/token-master),
both installed automatically. It composes with separately-installed open companions — e.g.
[Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills) — by recommendation.
