# Changelog

All notable changes to ATV-Phoenix are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`phoenix-deps` — dependency and supply-chain work gets a gate instead of a self-graded claim (#219).**
  Everywhere else Phoenix refuses to let an agent grade itself; dependencies were the one surface where
  "I updated the packages" was accepted on assertion, because nothing in `skills/`, `src/`, `scripts/`, or
  `.github/` owned that surface at all. The gate is not that the manifest changed — it is that the
  regenerated lockfile installs clean in a fresh environment the way CI will (`npm ci`,
  `pnpm install --frozen-lockfile`, `cargo build --locked`, `uv sync --locked`, `dotnet restore
  --locked-mode`), with the test suite still green afterwards. An incremental install is not the gate,
  because it passes on a lockfile CI will reject.

  Two rules that the state of the art states as craft are promoted here to gates, because both are
  dependency-shaped instances of laws this repo already has. **Stop at the no-op boundary** — no branch,
  no commit, no pull request when nothing needed changing — is the charter's no-op bias; an empty
  dependency PR costs a review cycle and teaches the team to skim dependency PRs, which is how the real
  one gets waved through. **A manager that could not be audited is BLOCKED and is named** is the
  silent-failure SLO: the defect is not the gap, it is the undisclosed gap, so coverage is reported
  beside the result and "clean across 4 of 6 managers, Maven and NuGet blocked" replaces "dependencies
  are clean". Remediation ranks by exploitation evidence rather than severity label — a High in CISA's
  KEV catalog outranks an unexploited Critical, because severity is a score and exploitation is a fact.

  The skill is routed from the `phoenix` meta-skill in the same change. An unrouted skill is this repo's
  costliest documented defect class — a correct mechanism wired to nothing — so
  `tests/test_phoenix_deps_skill.py` asserts the routing, not only the file's existence, and mirrors
  `doctor::check_skill_file`'s frontmatter rules so drift fails pytest and not only `cargo test`. Every
  assertion is paired with a negative fixture, including one proving that prose telling an agent to "run
  an objective check" fails the gate that requires a runnable `command_exit` block — the exact substitution
  of advice for enforcement the skill exists to end. Practice adapted from `jongio/skills` → `deps-doctor`
  (MIT), credited in the skill.
- **`Check.inputs` — a check can declare what it depends on, so a GREEN goes stale when that moves (#211).**
  `canonical_digest` folds the sha256 of every file named in `target`, so editing a test file the check
  names moves the digest and any recorded RED stops binding. It never saw what that file imports: a
  helper module, a fixture, the module actually under test. Those moved underneath a recorded GREEN and
  the GREEN kept asserting a world that no longer existed. Under `phoenix-mission` that is not
  hypothetical, because goals declare `depends_on`, so a sibling goal landing a commit is exactly this
  case and the DAG already knows it happened. `inputs` is where a check names those files; the digest
  folds them sorted by path and tagged by path, because a set of dependencies has no order and
  reordering a declaration must not change identity. A declared file that is missing folds the empty
  string, so deleting a dependency moves the digest instead of reading as though it was never declared.
  `tests/declared_inputs_move_the_digest.rs` pins the fold, the set semantics, the missing-file case and
  the end-to-end refusal: `accept` reports `ok=false` and `saw_red=false` once a declared input moves,
  while `currently_green` stays true, which is the trap the issue is about.

  **Existing digests do not move.** The `inputs_hash` key is inserted only when a check declares
  inputs. Adding it unconditionally would have changed the serialized string for every check in the
  repo and in every live trace, silently invalidating every recorded red→green. Two digests captured
  from `935abed` before the field existed are asserted as literals in that test.

  Getting there needed `Check` and `CheckKind` to derive `Default` and the 19 struct-literal sites
  across 13 files converted to `..Default::default()`, because Rust literals are exhaustive and a new
  field breaks all of them. That conversion is mechanical and carries no behaviour change; the budget
  exception for it was granted explicitly rather than taken. `CommandExit` is the default variant, and
  a default `Check` has an empty `target`, which #217 already made read RED for every kind.

### Fixed

- **Tier 3 now abstains when its instrument is UNKNOWN (#171).** The gate already disclosed a
  missing, void, stale, or saturated baseline but then compared against it anyway, allowing a
  below-baseline result from an invalid instrument to block a change. It now records the score and
  exits without accepting or rejecting; only a valid, fresh, non-saturated baseline can produce
  PASS or REGRESSION. The same valid fixture proves an unchanged arm is accepted and a deliberately
  regressed arm is rejected.

- **`sense` panicked instead of going RED when a check named no target (#211 groundwork).**
  `sense_command`, `sense_prompt_manifest` and `sense_ui_behavior` each guarded `target.is_empty()`
  and returned `ok: false`. `sense_sha256` and `sense_regex` did not: both indexed `check.target[0]`
  on entry, so an empty target panicked at `src/sense.rs:411` with an index-out-of-bounds rather
  than reporting a failure the caller could act on. The harness rests on `sense` returning failure
  as a value; a sensor that takes the process down removes the one signal an autonomous loop uses
  to tell success from failure, and removes it exactly when something has already gone wrong. Both
  kinds now return RED with evidence naming the empty target. `tests/empty_target_is_red_not_a_panic.rs`
  asserts the property across all five `CheckKind` variants, so a kind added later is covered by the
  same test rather than needing its own. This is also the precondition for #211 proper: adding
  `inputs` to `Check` means converting 19 struct-literal sites to `..Default::default()`, which means
  deriving `Default`, whose empty `target` would have handed every one of those sites a panic.

### Added

- **`phoenix_mission --backend mixed` — one mission, two backends (#86).** The decision layer for
  hybrid execution already existed: `HybridMission` routes, fences, and integrates, and
  `tests/hybrid_dag.rs` proved stale-cloud-result rejection and dependency-ordered integration in
  process. The execution layer did not. `src/bin/phoenix_mission.rs` accepted a single `--backend`
  for the whole mission, so no binary could run one goal locally and another in the cloud, and
  therefore no proof could observe the hybrid path from outside the process. `--backend mixed`
  routes per goal through a `RoutingBackend` that composes with the existing `GoalTaskBackend`
  rather than duplicating it: the task adapter rewrites the job, then routing decides where the
  rewritten job executes, so a routing table cannot silently change what a goal *does*, only where
  it runs. The run ledger records the backend that actually executed, because `BackendOutcome`
  carries its own `backend` field — that is what makes a mixed mission observable afterwards
  instead of merely asserted. Gated failure-first by `tests/test_hybrid_mission_e2e.py` (4 cases),
  which drives the real binary over `subprocess` and asserts only on evidence Phoenix produced (the
  run ledger, and the chains `phoenix-mcp verify-trace` audits); its cloud leg exercises the real
  `HttpCloudClient` over real HTTP against a local stub through the `COPILOT_API_URL` /
  `GITHUB_API_URL` seam `from_env` already honours, so the cloud path runs without creating a live
  Copilot job. Deliberately shaped against #139/#143: RED came from the property being false with
  the file present, not from a missing file. Restart-mid-mission and PostHog projection are **not**
  covered by this proof and are not claimed by it.

- **ARC skills are a typed view over the gated memory store (#186).** `evals/arc/skills.py` no
  longer keeps a private JSON aggregate. `SkillLibrary` admits every skill through
  `phoenix_learn.memory.Memory` and `phoenix_learn.accept.verify_gate`, so a skill is offered only
  after failure-first evidence (a red trial before a green one); a skill asserted with no such
  evidence is held pending and never returned by `available()`. Transferable skills persist to the
  `arc:corpus` scope and cross games; game-specific skills stay scoped to `arc:game:<id>`. Legacy
  `skills.json` rows still load, and only gate-passing rows are offered. Gated failure-first by
  `tests/test_arc_skills_memory.py` (3 cases).

- **`phoenix-mcp doctor --permissions [--fix] [--cwd <dir>]` — the MCP-approval facet.** Registration
  (`mcp-config.json`) makes the phoenix server *available*; *approval* (`~/.copilot/permissions-config.json`)
  is what lets a host actually **dispatch** its tools. A non-interactive (autopilot) host that finds phoenix
  registered-but-unapproved for the working folder denies `phoenix_sense` with *"could not request
  permission from user"* — and the harness silently stalls with no obvious cause. `doctor --permissions`
  detects that per-folder gap and prints exact remediation; `--fix` grants approval for all five phoenix
  tools, idempotently, preserving every other location/approval and backing up the prior config as
  `permissions-config.json.doctor-bak` (heal discipline). New public API `doctor::check_permissions` /
  `doctor::fix_permissions`; gated failure-first by `tests/permissions_doctor.rs` (4 cases). README now
  documents the denial + the CLI-mode fallback (`phoenix-mcp sense @check.json` hits the same gate ledger
  without needing the MCP approval).
- **The memory store crosses a process boundary.** `phoenix_learn.memory.Memory` gains
  `save(path)` and `Memory.load(path)`. The word cross-episode in #186 needs this: an ARC
  episode boundary is a process boundary, and a store held only in a dict forgets everything
  at exit, so it could not be the thing `evals/arc/skills.py` becomes a view over. `load`
  re-runs `verify_gate` over the trials it reads instead of trusting the verdict recorded
  next to them, so a claim hand-written into the JSON with only green trials is refused and
  its key is reported on `Memory.refused` rather than dropped in silence. That keeps the
  property the module exists for, that `remember` has no argument which skips the gate, from
  being walked around with a text editor. Retired facts are written too, because `evidence`
  answers across scopes and losing them at the file boundary would cost the record that makes
  re-earning one confirming trial. `save` builds the whole document before opening the file,
  so a value that will not serialize raises and leaves no truncated store behind. Issue #186.
- **Cross-episode memory that a fact has to earn.** `phoenix_learn.memory.Memory` stores a
  claim only when the trials behind it clear `phoenix_learn.accept.verify_gate`, so asserting
  a fact does not store it and there is no argument that skips the gate. Facts are keyed by
  scope and `enter(scope)` retires everything earned under the previous one, which is the
  storage half of the belief-invalidation rule in #181. The admitting trials and gate verdict
  stay with the fact, so `evidence(key)` answers across scopes and re-earning after a scope
  change is one confirming trial rather than a rediscovery. Domain-agnostic on purpose:
  `evals/arc/skills.py` keys on `game` and tags and is unusable by a shell or refactoring
  agent, which is the duplication #186 records.
- **`accept` says the digest moved instead of blaming the author.** When `verify_gate` finds no
  RED for a check's digest and the trace does hold RED sense rows under a different digest, the
  reason now names the digest, counts those rows, and points at the file-folding rule from #158
  as the cause. The old message told the author to reproduce a failure they had already
  reproduced, which is the message `phoenix-proof` printed on run 31201312829 of PR #172 when
  the check named a test file the pull request added. `ok`, `saw_red`, `green_after_red` and
  `currently_green` are computed exactly as before, so the gate refuses in the same cases it
  refused before and only the diagnostic changed. Closes part of #173; the base-sense fix
  itself is still an open design call on that issue. Issue #173.

- **An environment-characterisation primitive, so the next domain does not rebuild one.**
  `phoenix_learn.discover.characterise(actions, snapshot, apply, reset=None)` presses each
  action once, diffs the state, and reports what each one did. `diff_regions` says WHERE the
  state changed: a grid reports the bounding box of the differing cells plus how many differ,
  a mapping reports the changed keys, a flat sequence reports the changed indices. A 64x64
  grid that flips one cell no longer reads the same as one that repainted everything.
  `inert` names the actions that changed nothing, the cheap disproof the ARC traces show was
  never bought: one run pressed a single action 56 times on an untested theory that it
  advanced a timer and then died, and another spent 2,075 actions in one turn permuting 22
  orderings of a theory it never tested. The procedure costs one action per action.
  Aliases are reported only when a `reset` is supplied, because without one the actions run in
  sequence from whatever the previous action left behind, so `aliases_known` is False and the
  list stays empty instead of reading as evidence. The only dependencies are the two
  callables, so the same primitive covers an ARC grid and a shell agent whose state is the
  filesystem and the process table. Issue #183.

- **Seeds are part of the episodic gate's evidence.** `decide_episodic()` accepts a run as
  `{"score": float, "seed": hashable}`. A run that cannot name its seed cannot be re-run, so the
  verdict is the new `REJECT_UNREPRODUCIBLE` rather than green, and that objection outranks thin
  evidence because a sample nobody can reproduce is a worse problem than a sample that is small.
  Evidence is counted in DISTINCT seeds, so three runs at seed 42 are one observation rather than
  three. One seed producing two different scores is also unreproducible, which tests the
  determinism the gate had been assuming. `episodic_summary()` reports `baseline_seeds`,
  `candidate_seeds`, the distinct counts, `reproducible` and `unreproducible_reason`. Probed
  against the deployment on 2026-08-08: `temperature=0` and `top_p` are rejected with HTTP 400 and
  `seed` is honoured, reproducing byte-identical output. Issue #185.

- **An episodic adoption rule beside the row-based one.** `phoenix_learn.gate.decide()` needs
  `ADOPT_MIN_N = 20` held-out rows, and one ARC-AGI-3 run costs 4 to 10 minutes of real API spend,
  so clearing that bar is 2 to 3 hours of wall clock per decision. In practice `decide()` returned
  `EXPERIMENTAL_SMOKE_TEST` on every ARC call and gated nothing. `decide_episodic()` compares
  distributions instead of counting rows: the candidate's worst run must beat the baseline's median,
  which refuses a single lucky run by construction. `episodic_summary()` reports the numbers the
  verdict was made on without returning a verdict. Both samples need `EPISODIC_MIN_RUNS = 3`, and a
  verdict over zero runs is `EXPERIMENTAL_SMOKE_TEST` rather than clean. `decide()` is unchanged.
  Issue #184.

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
- **`phoenix-proof` fails when it has nothing to prove.** Every proof step in
  `.github/workflows/phoenix-proof.yml` is gated on `steps.acceptance_contract.outputs.declared == 'true'`,
  which on a pull request is true only when `.phoenix-ralph/done-check.json` exists on the head. With the
  file absent, `Require base acceptance RED`, `Require head acceptance GREEN`, `Prove Phoenix acceptance`
  and `Verify Phoenix trace` all skipped and the job still concluded SUCCESS, so any merge gate reading
  `statusCheckRollup` counted a run that proved nothing as satisfied. Measured on 2026-08-07 across the six
  then-open pull requests: all six reported `phoenix-proof COMPLETED SUCCESS` with every proof step skipped.
  A new `Require an acceptance contract` step now exits 1 on a pull request that declares no contract. The
  four proof steps keep their existing condition, so a run with no check file still does not try to read one.
  `tests/test_cloud_proof_workflow.py` asserts the guard exists, is scoped to `pull_request`, runs before
  the Rust build so a contract-less run stops early, and that removing it or pointing it at the wrong case
  makes the same validator fail. Issue #169.
- **The base acceptance sense keeps the head's acceptance tests, so a pull request can prove its own
  test.** `Require base acceptance RED` checked out the base commit and sensed there, which meant a check
  naming a test file the pull request adds saw a different file set on each side. Because #158 folds every
  file named in `target` into the check digest, the base and head observations carried different digests and
  `accept` reported `saw_red=false`. Moving the assertions into a file that already existed on base traded
  that for the opposite failure: base passed and the step refused the proof as vacuous. Both were measured on
  this branch, runs 31201312829 and 31201884178. The step now reads the test paths out of the check file,
  checks out the base commit, then restores those paths from the head before sensing, so the base observation
  measures the new test against the old code. Path extraction is restricted to `tests/*.py` with no parent
  traversal. Issue #173.
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

- **Red-before-fix gate on the dogfood harvester.** `scripts/harvest-datapoint.ps1` now replays
  `run_swe.ps1`'s scoring contract against the pre-fix task before writing it, and rejects the task
  unless `test_f2p` fails and `test_p2p` passes. Both failure modes were silent and both corrupt the
  Tier 3 baseline that gates merges: an f2p that already passes scores `resolved` with no fix applied,
  and a p2p that cannot pass makes the task unresolvable forever. The p2p arm also catches a solution
  in a language `run_swe.ps1` cannot score, since it scores every task with pytest. The gate runs after
  the PII lint so a rejected task still never touches disk. Issue #161.
- **`tests/test_harvest_datapoint.py` fixtures are now a real fail-to-pass task.** The suite previously
  harvested `def test_fix_passes(): assert True` against a `def broken(): return None` stub, so all
  eight tests proved file copying and nothing about whether a harvested task runs. The fixture is now a
  genuine off-by-one bug with an f2p that fails against it and a p2p that passes, and
  `test_red_before_fix_emitted_task_is_executable` replays the full resolved contract on the emitted
  directory: red before the fix, green after, with no p2p regression.
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
- **The Tier 3 gate discloses when its baseline is at the ceiling (#142).** `eval/scoreboard.json`
  records `arm_b_phoenix_resolved: 1.0` for swe-bench-lite, and `scripts/eval-gate.ps1` passes when
  the measured score is at least the baseline. A resolved-rate cannot exceed 1.0, so at that baseline
  the delta can never be positive: the gate detects a regression and cannot detect an improvement.
  Every run recorded since 2026-07-03 sat at exactly 1.0 with delta 0.0 and printed a bare
  `PASS: Arm B 1 >= baseline 1`. The gate now prints a `SATURATED` line naming the limit. Exit codes
  do not change, because the limitation is in what the number can show rather than in what should
  merge. `tests/test_eval_gate_discloses_ceiling.py` covers it, and asserts the line stays absent
  when the baseline has headroom, so an unconditional print cannot satisfy the guard.
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

- Replaced the wall-clock assertion in `tests/mission_concurrency.rs` with a direct occupancy observation, and shipped its negative control alongside it (#214). The old ceiling failed a genuinely concurrent run on a loaded machine, and because `cargo test` halts on the first failing binary that left 17 of 49 binaries unrun.

### Fixed

- **`Check.timeout_secs` is enforced, and evidence no longer panics the sensor (#205).** The field
  was part of the public MCP tool schema and was read nowhere: `sense_command` called
  `Command::output()`, which blocks until the child exits, so a check declaring a 2s bound against
  an 8s command returned GREEN after 14,505ms. A caller who sets a bound believes the check is
  bounded, and a check that never returns stalls an autonomous loop silently instead of going RED.
  Enforced with real termination — spawn piped, drain stdout/stderr on threads so a full pipe
  buffer cannot deadlock the wait, poll `try_wait` against the deadline, then kill the whole tree
  and reap it; killing only the direct child would trade a hung check for an orphan tree. `timed_out`
  and `exit_code` are now reported as independent facts, and `exit_code` is an `Option` because the
  old `unwrap_or(-1)` made "killed by the OOM killer" byte-identical to "exited -1". Separately,
  `truncate` sliced evidence at a fixed byte offset and panicked on a non-char-boundary. Gated by
  `tests/sense_timeout.rs`.

- **The acceptance contract restores every file it names, not only `tests/*.py` (#207).** #146 folds
  the sha256 of each existing target file into the check digest, so a file a pull request *adds* is
  absent on base, digests differently there, and `accept` finds no RED for the head digest — which
  refuses the ordinary write-the-failing-test-first shape. #172 mitigated that by restoring the head
  revision of the contract's acceptance tests onto the base tree, but recognised only paths matching
  `tests/*.py`, so a contract naming a gate script, a Rust integration test, or a test outside
  `tests/` still diverged: the same defect, just narrower. Anything path-shaped is selected now.
  Over-selecting is safe because the checkout tolerates a path absent at head; under-selecting is
  what breaks the proof. Bare binaries on `PATH` and flags are skipped, being nothing to restore.
  Fixes #173.

- **The eval gate enforces the instrument-validity rule the charter already stated (#208).**
  `MISSION.md` has said since 2026-08-07 that an eval gate whose measurement is missing, marked
  void, older than 14 days, or saturated at a perfect score is UNKNOWN. `scripts/eval-gate.ps1`
  disclosed saturation and checked nothing about age, so every merge since 2026-07-17 was gated
  against a baseline the charter already considered unable to discriminate, and the gate printed a
  bare PASS. That is the same defect class as #203 and #206: a rule advertised in one place and
  enforced nowhere. The void flag, the 14-day window, and the unparseable and absent cases are now
  checked, the last two being UNKNOWN for the same reason rather than silently skipped. UNKNOWN
  discloses and does not block — failing would stop the very pull requests that could refresh the
  baseline, which is the deadlock the rule exists to avoid. Gated by
  `tests/test_eval_gate_enforces_instrument_validity.py`.

- **`phoenix-proof` names a stale acceptance contract instead of failing late as vacuous.**
  `.phoenix-ralph/done-check.json` is repointed by each pull request at the check it turns
  red → green, but nothing noticed when a pull request inherited the previous one's contract.
  PR #186 shipped `evals/arc/skills.py` while the contract still named
  `tests/test_phoenix_memory.py`, a test PR #195 had already turned green on main and #186 never
  touched, so `Require base acceptance RED` sensed GREEN on base and exited 1 calling the proof
  vacuous — correct, but only after a full `cargo build --release`, and the message blamed the
  proof rather than the contract nobody repointed. A new `Require a fresh acceptance contract`
  step runs after `Set up Python` and before `Install Rust`: it reads the `tests/*.py` paths out
  of the head's contract and fails with that path list when the pull request changes none of
  them. A contract naming no `tests/*.py` path is left to the base RED gate as before, and the
  step is scoped to `pull_request` so `workflow_dispatch` runs, which synthesise their own check,
  are unaffected. `tests/test_cloud_proof_workflow.py` pins the guard, its position ahead of the
  Rust build, and that removing it, marking it `continue-on-error`, unscoping it from
  `pull_request`, or hollowing out its script makes the same validator fail.
- **`phoenix-doctor` is discoverable by Copilot CLI again.** Its frontmatter description contained an
  unquoted `: ` sequence, so Copilot's YAML loader rejected the skill even though `phoenix-mcp doctor`
  reported all shipped files healthy. The description is now quoted, and the doctor validator rejects
  this invalid plain-scalar pattern before it can ship again.

- **Concurrent Phoenix MCP checks can no longer fork or tear `trace.jsonl`.** Trace append now holds an
  OS-level exclusive file lock while validating the existing chain, selecting `prev_hash`, and writing
  one durable JSONL row. A malformed or broken trace fails closed instead of silently restarting from
  `GENESIS`, and regression coverage exercises 64 simultaneous writers.

- **The Tier 3 gate evidence in `tests/test_eval_gate_discloses_ceiling.py` can no longer disappear
  quietly.** `test_exit_codes_are_unchanged_by_the_disclosure` is this repository's only observation of
  `scripts/eval-gate.ps1` rejecting a deliberately regressed arm (exit 1) and accepting an unchanged one
  (exit 0), which is what issue #171 asks for. All three tests in the file sat behind a `_pwsh_available`
  probe that caught every exception and returned False, so a `subprocess.TimeoutExpired` on a loaded
  machine erased that observation and the suite still exited 0. Reproduced on 1eddf79 by forcing the
  probe to time out: 3 skipped, exit 0. The probe now returns False only for a genuine absence, raises
  `RuntimeError` on a timeout, and lets anything else propagate; the same forced timeout now gives 4
  failed, exit 1. Four tests pin it, one of which fails when the probe reports absence on a machine where
  `shutil.which` finds PowerShell. Same defect and fix as #170 (#171).

- **The PowerShell availability probe in `tests/test_harvest_datapoint.py` no longer turns an
  environment failure into a skip.** `_pwsh_available` caught every exception and returned False, so a
  `subprocess.TimeoutExpired` from a loaded machine read as "PowerShell is not installed" and eleven
  tests skipped themselves while the suite exited 0. Observed on 2026-08-07: five identical runs on one
  machine gave 13 passed, 13 passed, 8 passed with 5 skipped, 13 passed, 13 passed, with no code change
  between them. The probe now returns False only for a genuine absence, raises `RuntimeError` on a
  timeout, and lets anything else propagate. Reproduced both ways by forcing the probe to time out: the
  old code reported `1 passed, 12 skipped` and exit 0, the new code reports `13 failed, 4 passed` and
  exit 1. Four tests pin the behaviour, including one that fails if the probe ever claims PowerShell is
  absent on a machine where `shutil.which` finds it. The same probe is copied in
  `tests/test_auto_merge_gate.py` and `tests/test_north_star_runner.py` and is not touched here (#170).
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
