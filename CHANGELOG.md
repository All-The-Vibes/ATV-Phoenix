# Changelog

All notable changes to ATV-Phoenix are documented here.

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
