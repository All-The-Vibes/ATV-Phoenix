# The bundled skill pack — 16 skills, built from the ground up

These are **not** wrappers around someone else's pack. Every skill was written from scratch in the
[agentskills.io](https://agentskills.io) `SKILL.md` standard — each with an ASCII decision diagram, a
*Common Rationalizations* table, and a *Red Flags* section — and **every stage gates on an objective
`phoenix_sense` check**, so "simpler", "done", and "type-safe" are *proven*, not asserted. They install
automatically, and the harness validates them itself (`phoenix-mcp doctor`; `cargo test` fails on drift).

## Meta-router

| Skill | What it does |
|---|---|
| `phoenix` | Routes a task to the right lifecycle skill and enforces the non-negotiable Phoenix Laws. |

## The lifecycle — `think → ship`

| Skill | What it does |
|---|---|
| `phoenix-think` | Deep **Socratic interview + evidence-grounded research** → a crystal-clear Intent Contract whose deliverable is a *runnable* acceptance check. |
| `phoenix-plan` | Decompose the intent into small, individually-verifiable steps that keep the build green between them. |
| `phoenix-build` | Implement one step at a time under the verify-heal loop; never advance on a red check. |
| `phoenix-test` | TDD where the **test *is* the `phoenix_sense` gate** — failing test before code, bug repro before fix. |
| `phoenix-debug` | Systematic triage: reproduce objectively, isolate via the code graph, fix the *root*, confirm green. |
| `phoenix-context` | Assemble the cheapest sufficient context — route structural questions to the code graph (or an OKF bundle) instead of re-reading files. |
| `phoenix-review` | Re-run every check against the Intent Contract, confirm no regressions, inspect the tamper-evident trace. |
| `phoenix-ship` | The final gate — run the acceptance check once more, verify the trace, report success only on green evidence. |

## Craft — three masters distilled into objective gates

| Skill | Lineage | The objective gate |
|---|---|---|
| `phoenix-craft` | **Andrej Karpathy** — LLM coding pitfalls | think-first · simplicity · surgical changes — each *proven* by a `phoenix_sense` check, not asserted |
| `phoenix-typescript` | **Mat Pocock** — Total TypeScript | **`tsc --noEmit` *is* the check** — strict, derive don't duplicate, eliminate `any` |
| `phoenix-design` | **Emil Kowalski** — design-engineering | the **animation-decision framework** + a required **Before/After review table**, gated by lint/build/interaction checks |

## The spine — self-heal, token efficiency, open knowledge

| Component | What it does |
|---|---|
| `phoenix-self-heal` | The core **sense → snapshot → heal** loop on its own — for any change with a runnable test/build/lint. |
| `phoenix-okf` | Produce / validate / sense / consume **Open Knowledge Format** bundles — turn the code graph into browsable, git-diffable markdown, and ingest any external bundle as token-cheap context. See the [`demo`](../demo/okf/). |
| **TokenMasterX** (bundled, your own MIT plugin) | Graph-routed code navigation, **−73% tokens**; `phoenix-context` routes structural questions ("who calls X", "what breaks if I change Y") here instead of grepping whole directories. |

## Autonomous workflows — run-to-completion, gated by objective proof

| Skill | What it does |
|---|---|
| `phoenix-goal` | One fuzzy goal → **FORMALIZE** an objective acceptance check (no code until it exists) → decompose → drive to a proven outcome. |
| `phoenix-ralph` | Geoffrey Huntley's persistence loop (fresh context per iteration, filesystem as memory). Runs **interactively in-session** (the agent proves completion with `phoenix_accept`) or **unattended** via the external driver — either way completion is **proven from the trace**, never self-reported. |
| `phoenix-auto` | Dynamic state-sensing router — picks the next skill at runtime instead of a fixed pipeline, with oscillation + confidence guards. |

These rest on the **gate ledger** (`phoenix-mcp accept`): a check counts as done only if the
tamper-evident trace proves it went **red → green** (failure-first) and is green now — so a vacuous
`test -f` can't declare victory. See [`autonomous-workflows.md`](autonomous-workflows.md).

## The bundled stack (everything installs in one command)

Phoenix is standards-native ([agentskills.io](https://agentskills.io) skills + MCP). `setup.py` installs
the entire stack — nothing else to fetch:

| Layer | Component | Ships with Phoenix? |
|---|---|---|
| **Self-heal + full lifecycle + craft + autonomy** (the core) | The **16-skill verification-gated pack** enumerated above (router + `think/plan/build/test/debug/context/review/ship` + Karpathy/Pocock/Emil craft + self-heal + OKF + the `goal`/`ralph`/`auto` autonomous trio) | **Bundled** (`skills/`, installed automatically) |
| **Token-efficient retrieval** | [TokenMasterX](https://github.com/shyamsridhar123/TokenMasterX) — graph-routed code navigation (−73% tokens) | **Bundled** (`vendor/token-master`, installed automatically; needs `graphify`) |

The pack is **token-efficient by design** (structural questions route to the code graph; skill detail
loads only on activation) and **self-maintaining**: `phoenix-mcp doctor` validates every bundled skill
with Phoenix's own spine, and `cargo test` fails if any skill drifts — the harness verifies itself.
