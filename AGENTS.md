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
8. **SHIP via PR + AUTO-MERGE GATE** (`phoenix-ship`). Attach the `phoenix_verify_trace` / `phoenix_accept` result as
   evidence. Run `scripts/eval-gate.ps1` after push: exit 0 → merge (gh pr ready + gh pr merge --squash), exit 1 → leave draft + notify (regression), exit 2 → leave draft + notify (error). Docs/test-only: -Exempt flag. Never auto-merge: AGENTS.md/charter/prompts or blast-radius >3 files.
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

## Shipped connector inventory

The connector rows below are historical inventory, **not actionable backlog**. On 2026-07-17, their
acceptance suites returned exit 0 together (`23 passed, 1 skipped`) through `phoenix_sense`. Dreaming
must never seed an issue from this table.

| Connector | Current verification |
|---|---|
| **`phoenix-learn`** — GEPA/SIA-H over the trace ledger | `python -m pytest tests/test_phoenix_learn.py -q` |
| **Verify ⨯ Context** — TMX-scoped `phoenix_sense` | `python -m pytest tests/test_verify_context.py -q` |
| **Nest → Obsidian** — `phoenix-okf` vault emission | `python -m pytest tests/test_nest_emit.py -q` |
| **Scout adapter** (`dist/scout/`) | `python -m pytest tests/test_scout_install.py -q` |

## Current verified backlog

This is the **only** section Dreaming may use to seed an empty GitHub board. Every entry must state one
bounded outcome, stay within the blast-radius budget, and include a runnable `command_exit` done-check.
Before creating an issue, run that exact check through `phoenix_sense` against a clean `origin/main`
worktree:

- GREEN now → the entry is stale or shipped; do not create an issue.
- RED now → apply the Karpathy filter, then create `proposed` and promote to `ready` only if all gates pass.

### DO FIRST — connector proof CI enforcement

Add a CI workflow that runs the connector acceptance suite and rejects a broken Phoenix trace. This is
the previously documented enforcement gap after the first connector landed.

- **Scope:** `.github/workflows/connector-proof.yml` and `tests/test_connector_proof_ci.py`; no production
  behavior change.
- **Test contract:** parse the workflow and assert executable `run` steps invoke both
  `tests/test_phoenix_learn.py` and `phoenix-mcp verify-trace`; a fixture missing either command must fail.
- **Done-check (verified RED on 2026-07-17):**
  `python -m pytest tests/test_connector_proof_ci.py -q`

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
