# Changelog

All notable changes to ATV-Phoenix are documented here.

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
