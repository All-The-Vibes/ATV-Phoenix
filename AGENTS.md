# AGENTS.md — Build Charter: Phoenix builds Phoenix (self-hosting law)

> _Rises from its own ashes._ This repo builds the **lights-out software factory**. The factory is
> built **with the factory.** Phoenix is both the product and the build harness — we dogfood it on
> itself. If Phoenix can't reliably build Phoenix, the thesis ("the harness, not the model, makes the
> agent reliable") is false. Every connector merged green is direct evidence that it's true.

**Directive (Maverick, 2026-06-20):** all work on the factory connectors is built **under the Phoenix
lifecycle, gated by `phoenix_sense`.** This file is the binding contract. Any agent (GitHub Copilot or
Microsoft Scout) working in this repo reads it first and obeys it. Strategy/"why" lives in the Obsidian
note `Lights-Out Software Factory — OpenClaw, Phoenix & Continuous Learning.md`; what has shipped lives
in `README.md` / `CHANGELOG.md`.

---

## PII & privacy — never persist third-party people into this repo (non-negotiable, outranks the loop)
This repo is **PUBLIC**. A continuous-learning beat that scrapes real people into it is a privacy
breach, not progress — this rule outranks "compound knowledge" and the build loop below.
- **Never write third-party PII into any file, commit message, PR, issue, or gist.** Third-party PII =
  a real person's name, handle, email, or a verbatim/attributable quote lifted from a Teams/Discord
  channel, meeting, email, or DM. Capture the **idea**, never the **identity** — de-identify to
  "community signal," "a practitioner," "channel consensus"; strip the name and the verbatim wording.
- **WorkIQ / channel / mail content is private input, not publishable source.** Read it for context;
  persist only the de-identified substance.
- **Allowed:** the repo owner's own identity (name, copyright, repos) and legitimate open-source
  license attribution a dependency requires (e.g. an upstream author's MIT copyright).
- **Unattended beats self-censor by default:** if you would not paste a line into this public repo with
  the named person standing next to you, it does not get committed. When in doubt, omit the person.

## The non-negotiable loop (every change, no exceptions)

1. **FORMALIZE first** (`phoenix-goal`). No connector code until a **runnable `phoenix_sense` acceptance
   check** exists for it. *No objective check = no honest termination.* A connector without a formalized
   done-check is **not ready to start.**
2. **PLAN small steps** (`phoenix-plan`). Decompose into individually-verifiable slices in the ledger,
   ordered so the build stays green between steps.
3. **CONTEXT from the graph** (`phoenix-context` / TokenMasterX). Route "what calls X / what breaks if I
   change Y" to the TMX code graph (`graphify-nav/*`) — do **not** grep-and-reread whole files.
4. **SNAPSHOT before risky edits** (`phoenix_snapshot`). Only ever snapshot state that **passes** a check
   — never bless broken state.
5. **SENSE every step** (`phoenix_sense`). Binary GREEN/RED on an objective signal (exit code / file hash
   / regex). **Never self-judge.** Scope the test set by TMX's impact set where possible.
6. **HEAL on red** (`phoenix_heal`). Bounded rollback to the last snapshot + retry (more context / stronger
   model). **Never advance on red.** Escalate only when stuck.
7. **COMPLETION = PROOF** (`phoenix_accept`). A task is done **only when the hash-chained trace proves a
   check went red → green (failure-first) and is green now.** Never report "done" from the model's opinion.
8. **SHIP via PR** (`phoenix-ship`). Attach the `phoenix_verify_trace` / `phoenix_accept` result as
   evidence. **Human gate on risky changes. Never direct-commit** to the default branch.
9. **REMEMBER** (`phoenix-okf`). Promote the verified outcome into the OKF / Phoenix's-Nest bundle,
   indexed by TMX structural signature, so the next run retrieves it as cheap context.

**Enforcement (how this bites, not theater):**
- A connector PR that touches factory code **must** include a `phoenix_accept` (red→green) trace result.
  No trace, not mergeable.
- Each connector below has a **formalized acceptance check** recorded before work starts (see the session
  ledger / this file). "Ready to start" ⇔ a runnable done-check exists.
- Recommended hardening (not yet wired): a CI job that runs the connector's acceptance check + asserts a
  valid trace. Add it when the first connector lands.

---

## What we are building — the 3 connectors (+ the do-first)

The spine (`phoenix-mcp`, 5 tools), the skill family, both installers, and the OKF/Nest format are
**already shipped and installed.** "Build the factory" = wire **3 connectors** onto that.

| # | Connector | Acceptance check (the gate; formalize precisely before coding) | Order |
|---|---|---|---|
| **3** | **`phoenix-learn`** — GEPA/SIA-H over the trace ledger (port `goose/tools/gepa_optimize.py` + `sia_h_run.py`) | **MEASURED-GAIN GATE (Goose standard):** on a held-out **PRIVATE** split (3-way sha256, leakage firewall, anti-gaming lint), a candidate skill-diff is `ADOPT_ELIGIBLE` **only** at **n≥20, +10pp (or +2 net correct), ZERO right→wrong**; else `EXPERIMENTAL_SMOKE_TEST` and it adopts nothing. `phoenix_sense` is the **sealed grader** (candidates can't bring their own). `pytest tests/test_phoenix_learn.py` exits 0 **and** a red→green trace exists for the "reject un-gated / low-n diff" case. | **DO FIRST** (gap 15, the first dollar; no GPU, ~$2–10/run) |
| 1 | **Verify ⨯ Context** — TMX-scoped `phoenix_sense` | For a change to symbol X on a fixture repo, the gate runs **exactly** the tests in TMX's impact set for X (selected == graph-derived set; a test outside the set is not run). Assertion test exits 0. | after #3 has trace volume |
| 2 | **Nest → Obsidian** — `phoenix-okf` emits to a vault folder | After a verified fix, a valid **markdown + YAML-frontmatter** OKF bundle appears in the configured vault folder, parses, and is retrievable by TMX signature; re-emit is idempotent. `pytest tests/test_nest_emit.py` exits 0. | depends on #3 |
| — | **Finish Scout adapter** (`dist/scout/`) | `dist/scout` install registers the phoenix MCP into Scout's config and `phoenix_*` tools are callable in a Scout session (smoke check exits 0). | parallel, when Scout build needed |

**Architecture rules:**
- Monorepo owns the **spine + skills + OKF + host adapters**. `phoenix-learn` lands here as a Python
  package/skill.
- **TokenMasterX stays its own repo** (`../TokenMaster`) and composes via **MCP** — loose coupling is the
  feature (host-portable; already side-by-side in `~/.copilot/agents/`). Do not vendor it without cause.
- Skills/agents/instructions stay **portable markdown**; only the spine is Rust.

**SRE discipline — harvested from the live Goose loop (`Microsoft Scout/goose/`), enforced here:**
- **SLO:** silent-failure-rate (a beat claimed done while the objective check failed *and* it didn't disclose) is the headline metric over the trace ledger. **Always report coverage beside it** — a thin denominator must not pass as green. (ref `goose/tools/silent_failure_rate.py`)
- **Ledger integrity:** the hash-chained trace is the audit log; `phoenix_verify_trace` must **halt on a broken chain** (circuit-breaker), never write through it. (ref 39-row `CHAIN_OK` scorecard)
- **Controller is human-gated:** changes to the loop's own rules/prompts/charter are **PROPOSED** (timestamped RFC under a `proposals/` dir + notify), never self-applied; a human promotes. Tactics (a single skill/connector edit) may self-merge *only* through a red→green `phoenix_accept` trace.
- **Change criteria + cooldown:** a controller-level change needs the **same failure class across ≥3 runs**; ≤1 controller change / 24h.
- **Blast-radius budgets:** ≤3 files and ≤1 new skill per unit of work; "budget-capped" is a valid stop, not a failure.
- **No-op bias:** default to no durable change when there's no objective task — no busy-work churn.
- **Last-known-good:** keep a controller LKG (`phoenix_snapshot`) for one-step rollback.
- **Release hygiene:** conventional commits · `git pull --rebase` · never force-push. Backlog = GitHub issues with a label state machine (`ready` / `proposed` / `controller-proposal`+`human-gated`).

---

## Build vs. run (don't confuse them)
The PRODUCT runs on **GitHub Copilot** (and Microsoft Scout) — that's what users install. We BUILD it with
an autonomous agent under this charter. The build agent never ships to users; the harness does.
