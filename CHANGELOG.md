# Changelog

All notable changes to ATV-Phoenix are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Tier 3 scope is derived from the diff instead of asserted by the caller.** `scripts/eval-gate.ps1`
  previously waived the gate whenever a caller passed `-Exempt`, so whoever invoked the gate decided
  whether the gate applied. It now classifies the changed-file set and picks one of three outcomes
  already handled by charter STEP 7: exit 0 with `AUTO-EXEMPT` and the classified file list when no
  changed file is on the scored path, the normal eval run when any file is, and exit 2 with
  `NEEDS-HUMAN` when the diff changes `scripts/eval-gate.ps1`, `scripts/update-scoreboard.ps1`, or
  `eval/scoreboard.json`. Classification is fail-closed, so a path matching neither list is measured
  rather than exempted by omission. `-Exempt` survives as a human override and now logs that the
  waiver was asserted rather than derived. Issue #163.
- **`skills/**` is classified as behaviour, disclosed rather than blocked.** Skills are the agent's
  instructions, so a skill edit is the change most likely to move the Arm B resolved rate, and
  AGENTS.md line 48 currently waives it as docs. It no longer falls into `AUTO-EXEMPT`. Whether it
  blocks is decided by whether the meter can discriminate: while `baseline.swe_bench_lite.arm_b_phoenix_resolved`
  sits at 1.0 the gate prints `UNMEASURED`, names issue #142, and does not block, because a
  resolved-rate cannot exceed 1.0 and with n=9 a single stochastic failure reads as a regression.
  Once the baseline drops below the ceiling the same file is scored with no further edit. A skill
  change riding alongside a scored path does not drag that path into the waiver.
### Added
- **`pyproject.toml`, so the Python half installs with pip.** `pip install git+https://github.com/All-The-Vibes/ATV-Phoenix`
  failed with "neither 'setup.py' nor 'pyproject.toml' found", so a consumer of `phoenix_learn` had to add an
  absolute `sys.path` entry, which is machine-specific and breaks in CI, or vendor the whole repository as a
  submodule and then exclude roughly 300 upstream tests from its own collection root. The file declares the three
  existing packages, `phoenix_learn`, `phoenix_nest` and `phoenix_sense_tmx`, by name, because the repository root
  holds 17 top-level directories and setuptools flat-layout discovery refuses to guess among them. It declares no
  dependencies, because every import across the nine `phoenix_learn` modules is stdlib.
- **`tests/test_packaging.py`** compares the declared package list against the packages on disk, so a new root
  package that nobody declared fails the suite instead of silently missing from the wheel. It also checks the
  `pyproject.toml` version against `Cargo.toml`, which stops a second version source drifting unwatched, and builds
  a real wheel to confirm all three packages reach the artifact.

- **A validity marker on `eval/scoreboard.json` baseline blocks (#147).** Every result block under
  `baseline` now carries an explicit `valid` boolean, and a void block carries `invalidated_reason`.
  The 2026-07-03 `north_star` block is marked `valid: false`, because that run was broken and its
  results were never published. The numbers stay in the file so the history is still readable, and
  `_doc` says what the marker means. `tests/test_scoreboard_marks_invalid_runs.py` guards the schema
  and asserts `swe_bench_lite` is still `valid: true`, so marking the whole file void cannot satisfy
  the check. Before this, an agent read the orphan `north_star` block as evidence and wrote it into
  the README, which is the failure the marker exists to prevent.

- **`scripts/proof_status.py` answers whether a pull request's proofs actually ran (#138).**
  GitHub holds Actions runs at conclusion `action_required` on pull requests authored by the
  Copilot coding agent, so they queue and never execute. Ten pull requests merged on 2026-07-31
  and 2026-08-01 took that path. They were verified by hand in a scratch worktree, which is real
  verification that depends on a person remembering to do it. The script reads the check-run
  payload for a head SHA plus the changed-file list and exits 1 when a required proof is missing,
  held, or failed. `Phoenix proof` is required on every pull request because its workflow has no
  path filter. `Connector proof` is required only when a changed file matches the `paths:` block
  of `.github/workflows/connector-proof.yml`, so a docs change does not trip it.
  `tests/test_proof_status.py` covers it, including a test that fails when the path table drifts
  from the workflow file. This does not decide between the three fixes #138 lists; it makes the
  condition detectable either way.

- **Release-metadata enforcement in the local gate.** `scripts/release_drift.py` exits 1 when commits
  have landed since the version was cut and `## [Unreleased]` documents none of them. It anchors to the
  commit that last changed the version line in `Cargo.toml` rather than to a git tag, so the window
  between merging a release and pushing its tag is not red, and a shallow clone reports `unknown` rather
  than a failure it cannot justify. It runs git with every `GIT_*` variable stripped from the
  environment, because a git hook exports `GIT_DIR` and an inherited one makes `git -C <path>` answer
  for the hook's repository instead of the path it was given. Wired into both `scripts/ci-local.sh` and `scripts/ci-local.ps1`,
  along with `tests/test_version_consistency.py`, which shipped in 0.5.0 and which nothing was running.
- **`tests/test_release_drift.py`** covers the drift detection against throwaway git repositories and
  asserts the wiring itself: both ci-local entry points must invoke both release checks, and the two
  must gate the same targets. Its fixtures also run git with `GIT_*` stripped, and a regression test
  proves a fixture cannot commit into an inherited repository. An earlier version of the file lacked
  that isolation and committed its own fixtures onto the branch under test when the pre-push hook ran
  it.
- ORIGINAL_TAIL_MARKER

### Fixed

- `phoenix-mcp sense` and `phoenix-mcp accept` print a JSON usage error with `ok:false` and a
  `reason` and exit non-zero when called with no check argument, instead of panicking on an
  out-of-bounds index (#145).
- The `phoenix_mission` binary now runs a distinct task per goal instead of one constant for all
  four. A `FixedTaskBackend` rewrote every job to a single `MISSION_TASK` string, so the diamond
  DAG's four goals all executed the same command; under `--backend cloud` that one string became
  the problem statement handed to four separate Copilot coding agents. `GOALS` now carries a task
  for each goal, and a `GoalTaskBackend` adapter looks up each job's task by id before forwarding
  to the inner backend (#141).
- `scripts/ci-local.ps1` claimed identical checks to `scripts/ci-local.sh` while omitting the cloud
  workflow contract suite. Both now run the same eight stages.
- Gate-script integrity (issue #146) now folds the sha256 of every `target` element that names an
  existing file into a `command_exit` check identity, tagged by its position in the argument list,
  instead of only `target[0]`. The common check shape `["python","-m","pytest","tests/test_x.py"]`
  left the test file outside the digest, so a strict test could be recorded red, have its assertions
  gutted, and still chain to a later green because the check identity never moved. Files named
  directly in `target` are now pinned; files they import are not. Migration cost: this changes the
  digest of every existing `command_exit` check whose target names a file, so trace events recorded
  under the old digest stop matching and any in-flight red-to-green chain has to be observed again.
  Anyone mid-goal when this lands will see `accept` return `saw_red:false` on a check they believe
  they already drove red.

## [0.5.0] - 2026-08-01

**The mission runtime.** 0.4.0 proved Phoenix could build one connector under its own verify-heal
loop. 0.5.0 is what runs many of them: a supervisor that schedules goals under bounded concurrency,
executes them against either a local process or a GitHub Copilot cloud agent, fences stale holders
with leases, and records every run in an append-only ledger with a trace chain per goal. Alongside
it, the measurement stack that decides whether any of this is actually better than not having it.

94 commits since v0.4.0.

### Added

**Mission runtime.** The execution-backend contract (`src/execution_backend.rs`) with a local
backend that runs real argv processes rather than a placeholder dispatch (#97, #120), and a cloud
backend that submits jobs to the Copilot Agent Tasks API over a real HTTP client (#105, #121, #132,
#135). Backend selection reaches for cloud only when local is full and the goal is eligible (#102),
and preflight fails closed rather than dispatching into a backend that is not there (#99).

A bounded-concurrency supervisor ready queue admits at most `capacity` goals and defers the rest in
FIFO order, so the same sequence of calls always produces the same schedule (#98). Task identity
survives admission, deferral, and withdrawal (#124), and the done-check carries end-to-end
acceptance coverage rather than unit coverage alone (#126).

Leases fence stale goal holders with tokens (#101) and are reclaimed when a goal reaches a terminal
state (#110). Worktree isolation is mandatory for parallel workers (#113). Cancellation and
supersession are irreversible (#109). Per-goal and mission-wide budgets are enforced (#108).

Runs are durable: an append-only run ledger (#114), typed artifact fields instead of prose (#106),
structured artifacts captured during cloud dispatch (#107), and the model and usage the cloud remote
reports (#116). The supervisor and each goal get their own trace chain (#112).

Dependency-aware DAG readiness contains failure to the affected subtree (#118), and the hybrid
mission executor runs mixed local and cloud DAGs with SLA fencing and ordered integration (#127).
`phoenix::mission::run_mission` is the single composition root (#133), and the `phoenix_mission`
binary calls it rather than carrying a private second wiring (#137).

**Observability.** Derived run events and mission SLOs (#117), plus an optional privacy-safe PostHog
sink for that derived telemetry (#128).

**Learning.** The `phoenix-learn` optimizer proposes candidates behind the measured-gain gate that
0.4.0 shipped (#1), now using SkillOpt-style bounded edits with the gate itself unchanged (#131). A
graded Bayesian acceptance gate handles generative output where exact match does not apply (#18). A
typed signal to report pipeline dedupes incoming signals and measures post-merge outcomes (#129).

**Connectors.** The TMX scope interface (#2), Nest to Obsidian via `phoenix_nest.emit` (#3), and the
Scout adapter installer (#4).

**Sense.** Two new check kinds: prompt-manifest drift, which senses edits to the 18 skills and
`AGENTS.md` against a content-addressed baseline (#27), and `UiBehavior` for behavioural UI
acceptance (#15).

**Intent.** The `/intent` command decomposes one vague intent into N goals and accepts only on a
composite `phoenix_accept` across all of them (#25).

**Evaluation.** A SWE-bench-lite score tracker with a recorded baseline (#37), the Tier 3 auto-merge
gate `scripts/eval-gate.ps1` (#35), and an Azure north-star runner with a full inference and eval
pipeline (#36) using a repo-aware agent (#50). Dream traces are harvested into labeled eval
datapoints (#38). The paired harness protocol is preregistered (#76) with a pinned trial runner
(#87), evidence pins frozen before runs (#88), and failed model calls recorded rather than dropped
(#89).

**Ralph.** `phoenix-ralph-monitor.ps1` and the `phoenix-mcp monitor` subcommand give an objective
snapshot of a run (#10). Phase-aware proof bundles land as `completed.<digest>.json` (#11), with
`verify-live.mjs` and `verify-ui.mjs` gate templates (#11, #15) and a negative-assertion surface-scan
template (#13).

**CI.** Copilot cloud worker setup (#95) with a base-red head-green proof in CI (#96), and connector
proof integrity enforcement (#61).

### Changed

- Goal acceptance contracts are frozen, so a check cannot be edited into passing after the fact
  (#74).
- An incomplete TMX scope now requires the full test suite instead of a narrowed one (#93).
- `phoenix_learn` algorithm naming corrected, with qualified GEPA references enforced by a test
  (#125).
- README focused on verified core features (#91), with the Phoenix intent journey restored (#94) and
  the `phoenix_accept` claim corrected alongside two stated limits (#148).
- Formatting policy recorded: `cargo fmt` stays ungated (#6).

### Fixed

- The gate script's sha256 is folded into `canonical_digest`, so editing the script invalidates the
  check (#14).
- An unparseable trace row is treated as a broken chain rather than skipped (#115).
- Phoenix runtime state is isolated from git (#75).
- MCP struct tool arguments supplied as JSON strings are accepted (#149).
- `scripts/update-scoreboard.ps1` resolves its scoreboard path against the repository root instead of
  the caller's working directory, so Tier 3 results stop being discarded (#140).
- Ralph on PowerShell 5.1: guard, stdin prompt, and fail-fast spawn detection (#8); live-gate
  template with Windows stdio and case-insensitive matching fixes (#12); a warning when the
  done-check greens while backlog items remain unfinished (#13).
- North-star runner hardened with try/finally VM teardown, preflight, and an auto-shutdown net.
- `eval-gate.ps1` no longer passes `-Append:$False` across the `powershell -File` boundary, and the
  scoreboard preserves the north-star row on re-run.

### Removed

- The hybrid-mission end-to-end proof merged in #130, reverted in #143. It asserted its own
  hand-built fixtures and executed none of `src/mission.rs`, `src/lease.rs`, or the binary.
  `tests/test_e2e_proof_is_not_vacuous.py` now guards against its return. The lesson is recorded in
  the issue: RED from a missing file is not RED from a failing assertion, and the harness cannot tell
  them apart.
- The Score Tracker section in the README.

### Security and privacy

- Third-party PII scrubbed from `BUILDLOG` and `MISSION`, with verbatim channel quotes paraphrased.
- A non-negotiable PII and privacy rule added to the build charter, outranking the build loop.

## [0.4.0] - 2026-06-20
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

## [0.3.1] - 2026-06-19
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

## [0.3.0] - 2026-06-10
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

## [0.2.0] - 2026-06-10
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

## [0.1.0] - 2026-06-09
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

[Unreleased]: https://github.com/All-The-Vibes/ATV-Phoenix/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/All-The-Vibes/ATV-Phoenix/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/All-The-Vibes/ATV-Phoenix/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/All-The-Vibes/ATV-Phoenix/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/All-The-Vibes/ATV-Phoenix/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/All-The-Vibes/ATV-Phoenix/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/All-The-Vibes/ATV-Phoenix/releases/tag/v0.1.0
