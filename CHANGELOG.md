# Changelog

All notable changes to ATV-Phoenix are documented here.

## [Unreleased]

### Added
- **Prompt-manifest drift sense — the "living prompt document"** (`src/prompt_ledger.rs` + a fourth
  `CheckKind::PromptManifest`). Captures Phoenix's own prompt surface (the 18 skills + `AGENTS.md`) into a
  content-addressed manifest, then SENSES drift against it: GREEN when the surface matches the blessed
  baseline, RED — naming the added/removed/changed files — on any edit. Because it is an ordinary `Check`,
  it inherits the whole spine: `phoenix_accept` proves a prompt check went **red → green**, the trace audits
  it. The self-owned, verification-gated analog of a "living system-prompt document" — Phoenix refuses to
  silently accept edits to what steers it. Built failure-first through the real `phoenix-mcp` binary:
  `cargo test --locked prompt_ledger` sensed **red → green**, `phoenix_accept` returned ok=true (trace
  intact, `check_digest 4fa0e55c`). Committed living document: `docs/prompt-ledger/phoenix-prompts.json`
  (regenerate with `cargo run --example capture_prompts`). (#27)

## [0.4.0] — 2026-06-20

**The factory turns on itself.** Phoenix builds its first *connector* — and builds it *with* Phoenix: the
change was driven failure-first through the shipped `phoenix-mcp` binary and merges only behind a
tamper-evident **red → green** `phoenix_accept` trace. Plus the governance + **local-first CI** that lets
the factory run on ~zero GitHub Action credits.

### Added
- **`phoenix-learn` — the measured-gain adoption gate** (C3, `phoenix_learn/`: `gate.py` + `split.py`),
  ported from the live continuous-learning loop. A candidate skill/prompt diff is `ADOPT_ELIGIBLE` **only**
  on a held-out PRIVATE split at **n ≥ 20** with **+10pp** (or **+2** net correct) accuracy, **zero
  right→wrong** regressions, and strictly better than baseline; an anti-gaming hit short-circuits to
  `REJECT_GAMING_DETECTED`, thin evidence to `EXPERIMENTAL_SMOKE_TEST`, everything else to `REJECT`. Ships
  with a deterministic sha256 3-way split (PRIVATE scored once), a leakage firewall, and an anti-gaming
  lint. The gate **decides eligibility; it never adopts** — adoption stays human-gated. Built failure-first
  under the Phoenix loop: `tests/test_phoenix_learn.py` (9 deterministic, offline, zero-LLM cases) sensed
  **red → green** via the real `phoenix-mcp` binary; `phoenix_accept` returned ok=true (failure-first
  satisfied, trace intact, `check_digest 441a68e4`). This is the **first slice** — the gate core; the
  optimizer that *proposes* candidates is next. (`evals/c3-phoenix-learn/RESULT.md`)
- **Build charter — "Phoenix builds Phoenix"** (`AGENTS.md`): the self-hosting law (every connector is
  built under the verify-heal loop and merges behind a red→green `phoenix_accept` trace), the connector
  acceptance-check table, and the KERNEL's SRE rules (SLO, halt-on-broken-chain, human-gated controller,
  blast-radius budgets, no-op bias, last-known-good, release hygiene) folded into how the factory governs
  itself.
- **Local-first CI** (`scripts/ci-local.{sh,ps1}` + `.githooks/pre-commit` & `pre-push`): the full gate
  (cargo test `--locked` + OKF pytest + the `phoenix-learn` gate + OKF-bundle conformance ×2) runs
  **locally**; the pre-push hook blocks any red push, pre-commit runs a fast `cargo check` when Rust is
  staged. Managed backlog on the org **"Phoenix Factory"** project (a 12-label state machine, issues, and
  roadmap/RFC gists).

### Changed
- **CI workflows now spend ~zero Action credits.** `.github/workflows/rust.yml` + `okf.yml` are trimmed to
  `workflow_dispatch`-only (no push/PR auto-trigger); the identical checks are enforced by the local gate
  above. The credit constraint is met without giving up the gate.
- `scripts/ci-local.{sh,ps1}` broadened to run the C3 `phoenix-learn` test as a first-class gate step.

## [0.3.1] — 2026-06-19

Self-maintenance: Phoenix now verifies and repairs its **own install** with the same objective discipline
it gives the agent — plus the fix for the agent that silently wouldn't load.

### Fixed
- **`copilot --agent phoenix` → "No such agent: phoenix"** for everyone who installed before this release.
  The shipped agent's inline MCP-server entry was missing the required `args:` field, so Copilot silently
  dropped the agent at load time (other agents with `args:` loaded fine — proven 3/3 in an isolated
  `COPILOT_HOME` sandbox). `dist/phoenix.agent.md` and the installer template now include `args: []`.
  Already installed before today? Run `phoenix-mcp doctor --fix`. (`e4cebe3`)

### Added
- **Install-integrity doctor + self-repair** (`phoenix-mcp doctor [--fix] [--home]`, `src/doctor.rs`):
  compares the *installed* agent, skills, and MCP registration against what THIS build ships (embedded at
  build time by `build.rs`) and reports drift as objective `{check, ok, evidence, problems}` results.
  `--fix` re-syncs from the embedded reference, snapshots the prior agent + mcp-config as `*.doctor-bak`
  first (heal discipline), is idempotent, and is re-verified **red → green**. Detection is **generic**
  (content-hash comparison, no per-field hardcoding) — so it caught the missing-`args` bug above and will
  catch the next schema change too.
- **`phoenix-doctor` skill** (bundled pack now **18**): a thin UX over the engine — diagnose, explain the
  failures, drive `--fix` with confirmation, and confirm with the authoritative `copilot --agent phoenix`
  load test as the `--deep` proof.
- **Regression gate** (`tests/install_doctor.rs`, 4/4): seeds the *exact* pre-fix broken agent and asserts
  doctor flags it as drift, `--fix` repairs it to match shipped, the fix is idempotent, and a missing skill
  / unregistered MCP server are caught — plus a meta-assertion that the detection logic names no specific
  field.
- **Doctor is self-surfacing.** When the agent won't load or a skill goes missing, the loaded agent, the
  installer's final message, and the README troubleshooting all point to `phoenix-mcp doctor --fix` — so a
  user who has never heard of the doctor still finds the cure (closes the discovery loop on the bug above).
- **Build-freshness check.** `doctor` now also verifies the running `phoenix-mcp` binary was built from the
  repo's current `HEAD` — closing the one blind spot the integrity check structurally can't see: integrity
  compares the install against the *binary's* embedded reference, so a binary that is itself behind the source
  would report the install "healthy" against a stale truth (the exact trap where a fresh commit lands but the
  old binary still validates green). `build.rs` stamps the build commit; the doctor compares it to `git HEAD`
  and prints a `build:` line (`up_to_date` / `behind` / `unknown`). Staleness is fixed by `cargo build
  --release` (not `--fix`), and both the JSON and the exit code reflect it. (`tests/build_freshness.rs`, 4/4)
- **Linux CI** (`.github/workflows/rust.yml`): builds `--locked` and runs the full test suite (incl. the
  install-integrity regression gate) on ubuntu, closing the gap the OKF-only workflow left — a
  green-on-Windows change can't silently break the cross-platform path. Actions pinned to current majors
  (`actions/checkout@v7`, `actions/setup-python@v6`), off the deprecated Node 20 runner (also bumped on
  `okf.yml`).

### Changed
- **Autonomous entry no longer wanders.** `phoenix-goal` now opens every hands-off run with a required
  **FRAME handshake** — restate the goal, name the objective done-check it will formalize (and that it
  starts RED), say how to steer/stop, and confirm before the first edit. An autonomous alias from another
  harness gets oriented to the real entry point instead of a silent "I'll operate in its spirit"
  improvisation (the discipline now lives *in* the skill that runs, not only in the router). The router's
  entry guidance leads with the canonical `/phoenix-goal "<goal>"`.
- **Single source of truth for the agent**: `setup.py` now reads `dist/phoenix.agent.md` (so the embedded,
  installed, and on-disk copies are one source); removed the duplicate inline Python template that had
  drifted out of sync. The post-install self-check now runs the **full** integrity doctor (agent + skills +
  MCP registration), not skills-only.
- Docs updated **16 → 18 skills** (README, `docs/skills.md`, the `phoenix` router decision tree, and the
  installer's summary line).

## [0.3.0] — 2026-06-10

Autonomous workflows — the same capabilities as Claude Code's ralph/autopilot, but gated by objective,
tamper-evident proof instead of an LLM's opinion. Grounded in researched primary sources
(`research/autonomous-workflows-research.md`).

### Added
- **Gate ledger** (`src/accept.rs`) — completion is **derived from the trace, not authored**: a check
  counts as done only if the tamper-evident trace proves it went **red → green** (failure-first) for the
  same canonical check and is green now. Rejects vacuous (never-red) checks and tampered traces.
  Available **both as an MCP tool (`phoenix_accept`)** for the interactive in-session loop **and a CLI
  command (`phoenix-mcp accept`)** for the unattended driver. New `canonical_digest(&Check)` makes a
  check identifiable identically across the MCP path, CLI path, and ledger. (`tests/gate_ledger.rs`, 3/3.)
- **Three autonomous-workflow skills** (pack now 16): `phoenix-ralph` (Huntley's persistence loop —
  fresh context per iteration, filesystem as memory; runs **interactively in-session** via the
  `phoenix_accept` tool, or **unattended** via the external driver), `phoenix-goal`
  (formalize an objective acceptance check, then decompose + drive), `phoenix-auto` (dynamic
  state-sensing router with oscillation + confidence guards). The base `phoenix` router stays a stable
  fixed tree and dispatches to these only in autonomous mode.
- **Ralph loop driver** (`dist/ralph/phoenix-ralph.ps1` + bash twin): the external loop (Copilot/Scout
  are one-shot — no re-injection hook). The **driver owns** the loop/wall-clock/no-progress budgets, the
  pre-turn accept, the trace-intact check, and the proof bundle + git tag; the agent only proposes. With
  PROMPT/backlog/done-check templates under `dist/ralph/`.
- **`@file` arg convention** for `phoenix-mcp sense|accept|snapshot|heal` — reads the check JSON from a
  file, sidestepping PowerShell→exe quote-mangling of inline JSON.
- Docs: `docs/autonomous-workflows.md` (design) + `research/autonomous-workflows-research.md` (sourced).
  Eval + screenshot: `evals/autonomous-workflows/`.

## [0.2.0] — 2026-06-10

The "everything composes" release: a comprehensive bundled skill pack, vendored TokenMasterX, a
real end-to-end build, and a SWE-bench-style benchmark.

### Added
- **13-skill verification-gated pack** (`skills/`): a `phoenix` meta-router (6 Phoenix Laws) + the full
  lifecycle (`think → plan → build → test → debug → context → review → ship`) + `phoenix-self-heal` +
  three craft skills distilling the masters — `phoenix-craft` (Karpathy), `phoenix-typescript`
  (Mat Pocock, `tsc --noEmit` as the gate), `phoenix-design` (Emil Kowalski). `phoenix-think` is a deep
  interview + deep-research skill that produces the Intent Contract before any code.
- **Self-maintenance**: `phoenix-mcp doctor` validates every bundled skill with Phoenix's own spine;
  `cargo test` (`tests/skills_doctor.rs`) fails if any skill drifts.
- **Bundled TokenMasterX** (vendored MIT © 2026 Shyam Sridhar, `vendor/token-master`) — installed
  automatically by `setup.py`.
- **End-to-end build evidence** (`evals/e2e-sandbox/`): live Copilot built a working Space Invaders game
  under the Phoenix loop, gated by an objective check + a hardened Playwright interaction gate
  (`evals/benchmark/play_check.js`).
- **SWE-bench-style lite benchmark** (`evals/swe-bench-lite/`): the SWE-bench resolved contract
  (FAIL_TO_PASS + PASS_TO_PASS) on 9 self-contained tasks, two arms. Underspecified tier **50%→100%**,
  overall **78%→100%**, 0 regressions; both vanilla misses were silent failures.

### Changed
- `setup.py` now installs the whole stack in one command (binary, MCP registration, 13 skills, doctor
  self-check, bundled TokenMasterX).
- README consolidated: full evidence table, the Intent-to-Outcome ("radio *for* TV" — a new medium
  still running the old format) framing + concept doc (`docs/intent-to-outcome.md`),
  honest bundled-vs-companion stack, hero + loop imagery.
- `dist/install.ps1` now registers the MCP server (was agent-only).

## [0.1.0] — 2026-06-09

First shippable release. A self-healing harness for AI coding agents, multi-host (GitHub Copilot + Microsoft Scout).

### Added
- **Self-healing spine** (`phoenix` Rust lib): objective `sense` (command-exit / file-sha256 / regex),
  blessed `snapshot` (only saves a known-good state), bounded `heal` (rollback / retry ≤3, confirmed by
  an external recheck), and a tamper-evident hash-chained `trace` with `verify`.
- **MCP server** (`phoenix-mcp`): stdio JSON-RPC server (rmcp 1.7) exposing `phoenix_sense`,
  `phoenix_snapshot`, `phoenix_heal`, `phoenix_verify_trace` to GitHub Copilot via `/mcp`.
- **CLI mode** (same binary): `phoenix-mcp sense|snapshot|heal|verify-trace '<json>'` with pass/fail exit
  codes — the adapter for hosts without external-MCP support (Microsoft Scout, via its shell tool).
- **Install**: `dist/phoenix.agent.md` + `dist/install.ps1` (Copilot); `dist/scout/` (Scout skill).
- **Evidence**: milestone evals + screenshots (M1–M3, H2) under `evals/`.

### Proven
- M1: behavioral self-heal (`cargo test`, non-tautological — recovery judged by an external signal).
- M2: full sense→heal→verify over real MCP stdio JSON-RPC.
- M3: a live GitHub Copilot session autonomously sensed + healed a fault; file fixed on disk; traced.
- H1: criteria-first verification lifts verified-outcome rate by +0.125 (mean), replicated across 3/3 runs.
- H2: across 20 live Copilot sessions, Phoenix cut the silent-failure rate from 40% to 0% on tasks with
  hidden acceptance criteria, with zero regressions.
- H3: injecting a project's convention lifted Copilot from 0% to 100% on tasks whose correct output is
  unguessable from the spec alone.

### Install & DX
- One-command install via `.copilot-plugin/skills/phoenix-setup/setup.py` (idempotent: builds binary,
  registers MCP server, installs agent).
- Dogfooding fix: `sense` inputs are now lenient (`target` accepts a string or array; `expect` accepts
  an int, string, or null) with an example in the tool description — cut a measured live run from
  72 credits / ~25 failed calls to 15 credits / 4 calls.

### Known limitations
- `command_exit` timeout documented but not yet enforced in-process.
- `tokens_in/out` not yet captured (the host doesn't expose per-call counts to the server).
- `--agent phoenix` requires marketplace/plugin registration; live use today is via MCP-config registration.
- Results are directional (small n, single model, deterministic checkers).

### Added (skills + self-maintenance)
- Bundled, verification-gated lifecycle skill pack (skills/): phoenix-spec / plan / build / review /
  ship + phoenix-self-heal — every stage gated by an objective phoenix_sense check.
- phoenix-mcp doctor + src/doctor.rs: Phoenix validates its own bundled skills (self-maintenance);
  cargo test fails on skill drift. setup.py installs all bundled skills and runs the self-check.
