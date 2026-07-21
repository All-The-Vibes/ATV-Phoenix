<p align="center">
  <img src="assets/logo.jpg" width="104" alt="ATV-Phoenix logo: an ember-orange phoenix on a dark background">
</p>

<h1 align="center">ATV-Phoenix</h1>

<p align="center"><strong>Copilot proposes the code. Phoenix decides whether the evidence is good enough.</strong></p>

<p align="center">
  Phoenix is a verification and recovery harness for GitHub Copilot and Microsoft Scout.
  It runs real checks, recovers from failures, and records proof that the work went from failing to passing.
</p>

<p align="center">
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.4.0-E07000" alt="Version 0.4.0"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-00B4D8" alt="MIT license"></a>
  <a href="Cargo.toml"><img src="https://img.shields.io/badge/core-Rust-E07000" alt="Rust core"></a>
  <a href=".github/workflows/connector-proof.yml"><img src="https://img.shields.io/badge/proof-failure--first-00B4D8" alt="Failure-first proof"></a>
</p>

<p align="center">
  <a href="#intent-engineering-across-three-loops">Journey</a> |
  <a href="#install">Install</a> |
  <a href="#quick-start">Quick start</a> |
  <a href="#core-features">Features</a> |
  <a href="#evidence">Evidence</a> |
  <a href="#documentation">Docs</a>
</p>

Phoenix replaces "the agent says it is done" with an external control loop:

1. Define a runnable acceptance check.
2. Observe the check fail.
3. Let the agent edit and recover.
4. Re-run the same check.
5. Ship only when the hash-chained trace shows the check was red before the fix, turned green
   afterward, and is still green on the final recheck.

Use Phoenix for bug fixes, refactors, PR work, and unattended jobs where a runnable check can define
the outcome.

<p align="center">
  <img src="assets/journey.png" width="760" alt="INTENT IN. OUTCOME OUT. Phoenix intent engineering across inner, outer, and learning loops">
</p>

## Intent engineering across three loops

Phoenix converts a raw request into an **Intent Contract** before implementation. `phoenix-goal`
formalizes one goal; `phoenix-intent` decomposes up to five related goals. Each gets a runnable
acceptance check that must be observed RED before code changes begin. `phoenix-plan` turns the
contract into checked backlog items. Changing the check later is an explicit re-scope and requires a
new RED baseline.

- **Inner loop: self-healing** - one change. `phoenix_sense` checks state, `phoenix_snapshot` saves only
  a passing baseline, and `phoenix_heal` rolls back or retries up to three times. Recovery counts only
  after an external recheck passes.
- **Outer loop: goal execution** - one goal. `phoenix-auto` selects the next lifecycle step while
  `phoenix-ralph` works the checked backlog across fresh contexts, filesystem memory, and fixed budgets.
  The loop stops only when `phoenix_accept` proves the top-level check went RED to GREEN.
- **Learning loop: measured improvement** - many verified runs. `phoenix_learn` uses public data to
  propose, development data to select, and a held-out private split to measure the selected candidate
  once. Eligibility requires at least 20 held-out examples, a 10-point gain, +2 net correct, zero
  regressions, and clean anti-gaming checks.

This is **self-learning, not self-modifying**. The gate decides eligibility; it never adopts. A human must
approve any skill or prompt change, which then needs its own failure-first Phoenix proof.

## Install

> Requires Git, [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-in-the-cli),
> Python 3, and [Rust](https://rustup.rs).

```powershell
git clone https://github.com/All-The-Vibes/ATV-Phoenix
cd ATV-Phoenix
python .copilot-plugin/skills/phoenix-setup/setup.py --repo .
```

The installer builds `phoenix-mcp`, registers the MCP server, installs the Phoenix agent and skill
pack, and runs an install-integrity check. It also attempts to install TokenMasterX, the maintainer's
graph-routing plugin. TokenMasterX requires `graphify` on `PATH`; setup prints the exact follow-up
command when that optional dependency is missing. Restart the Copilot CLI session after setup.

If an upgrade or host change breaks the install:

```powershell
# Windows
.\target\release\phoenix-mcp.exe doctor --fix

# macOS / Linux
./target/release/phoenix-mcp doctor --fix
```

## Quick start

Start Copilot with the Phoenix agent:

```powershell
copilot --agent phoenix
```

This starts an interactive session. Phoenix acts on the task you give it; it does not start an
unattended loop by itself. If the agent does not load, run `phoenix-mcp doctor --fix`, restart
Copilot, and retry.

Give it a task with a concrete check:

```text
Fix the failing test. Use `python -m pytest tests/test_widget.py -q` as the
acceptance check. Do not finish until phoenix_accept proves red to green.
```

Phoenix should:

- run the check and record the failing result;
- edit the smallest relevant surface;
- re-run the same check;
- recover or roll back if it stays red;
- call `phoenix_accept` only after the trace proves the check went red to green.

The audit trail lives in `.phoenix/trace.jsonl`. Verify it directly with:

```powershell
# Windows
.\target\release\phoenix-mcp.exe verify-trace

# macOS / Linux
./target/release/phoenix-mcp verify-trace
```

The MCP completion tool is `phoenix_accept`. Its direct `phoenix-mcp accept` CLI form is:

```powershell
.\target\release\phoenix-mcp.exe accept @check.json
```

For a full first project walkthrough, see the
[developer journey](docs/developer-journey.md).

## Core features

### The proof stack

| Capability | What it does |
|---|---|
| **1. Intent engineering** | `phoenix-goal`, `phoenix-intent`, and `phoenix-plan` convert direction into checked contracts and backlogs before implementation starts. |
| **2. Objective checks** | `phoenix_sense` evaluates command exits, file hashes, regexes, prompt manifests, and UI behavior without asking an LLM to grade itself. |
| **3. Self-healing** | `phoenix_snapshot` saves only passing state. `phoenix_heal` performs bounded rollback or retry, then confirms recovery with an external recheck. |
| **4. Proven completion** | `phoenix_accept` rejects vacuous checks and returns success only when an intact trace proves failure first and success now. |

### Beyond the core loop

| Capability | What it does |
|---|---|
| **Long-horizon execution** | `phoenix-goal` formalizes the finish line, `phoenix-auto` chooses the next lifecycle step, and `phoenix-ralph` persists across fresh-context iterations. |
| **Graph-aware context** | `phoenix-context` asks TokenMasterX for call relationships and change impact instead of repeatedly scanning whole directories. |
| **Portable knowledge** | `phoenix-okf` turns code and external knowledge into Open Knowledge Format (OKF) bundles: linked Markdown that can be validated, reviewed, and reused. |
| **Measured learning** | `phoenix_learn` evaluates candidate prompt and skill improvements on held-out outcomes; adoption remains human-gated. |
| **Install integrity** | `phoenix-mcp doctor` detects drift in the agent, skills, MCP registration, and binary freshness, then repairs it with `--fix`. |
| **Multiple hosts** | GitHub Copilot uses the MCP server and agent pack. Microsoft Scout uses the same Rust binary through the CLI adapter in [`dist/scout`](dist/scout). |

Browse the documented lifecycle in [`docs/skills.md`](docs/skills.md). Skill names use hyphens
(`phoenix-goal`); MCP and CLI tool names use underscores (`phoenix_sense`).

<p align="center">
  <img src="assets/loop.jpg" width="520" alt="Phoenix sense and heal loop with passing and failing branches">
</p>

The trace, not the model's success message, is the source of truth.

## Autonomous workflows

- **Interactive:** `copilot --agent phoenix` works on the task and permissions you provide.
- **Autonomous:** [`phoenix-goal`](skills/phoenix-goal/SKILL.md) formalizes the outcome,
  [`phoenix-auto`](skills/phoenix-auto/SKILL.md) routes by objective state, and
  [`phoenix-ralph`](skills/phoenix-ralph/SKILL.md) persists across fresh contexts and fixed budgets.

See [`docs/autonomous-workflows.md`](docs/autonomous-workflows.md) for state files and drivers.

## Evidence

Phoenix ships its evaluation inputs and outputs in the repository. The results are directional,
not universal claims.

| Evaluation | Result | Scope |
|---|---|---|
| [Pinned paired harness](evals/harness-eval/results/run-manifest.json) | Phoenix **38/45** objective passes vs control **34/45**; silent failures **7/45** vs **11/45** | 90 real `gpt-5.6-sol` calls, 9 tasks, 5 seeds, paired arms, independent sealed and adversarial checks |
| [Silent-failure experiment](evals/h2-experiment/RESULT.md) | Silent failures **40% to 0%**, with zero regressions | 20 live Copilot sessions, one older model/CLI configuration, deterministic checkers |
| [SWE-bench-style evaluation](evals/swe-bench-lite/RESULT.md) | Overall resolved rate **78% to 100%**; underspecified tier **50% to 100%** | 9 constructed tasks, one repetition, explicit test gate in the Phoenix arm; not the official SWE-bench dataset |
| [OKF evaluation](evals/m4-okf/RESULT.md) | Index-first retrieval used **31x fewer tokens** than raw `graph.json` | 50-file bundle; benefit is strongest across repeated and larger-context work |
| [Measured-learning gate](evals/c3-phoenix-learn/RESULT.md) | Candidates need **n >= 20**, **+10 percentage points**, **+2 net correct**, and **zero regressions** | Deterministic offline gate; it decides eligibility and never auto-adopts |

The paired harness stores the exact source commit, model, runner, environment, task-set, seed,
verifier, and raw-run hashes. Inspect
[`raw-runs.jsonl`](evals/harness-eval/results/raw-runs.jsonl) for every row.

## What ships

- Rust MCP and CLI spine plus a verification-gated lifecycle skill pack.
- PowerShell and Bash Ralph drivers, Copilot setup/repair, and a Microsoft Scout adapter.
- Measured-gain learning gate plus TokenMasterX graph integration from the same maintainer.
- Reproducible tests, raw evidence, and the full [`BUILDLOG.md`](BUILDLOG.md).

## Honest limits

- Phoenix proves the check you give it. A weak check can still prove the wrong outcome.
- Recovery is bounded rollback and retry, not general autonomous repair.
- Command timeouts are represented in checks but are not yet enforced in-process.
- The published evaluations use small constructed task sets and single models. Treat the deltas as evidence for these conditions, not as a universal ranking.
- Phoenix runs when you invoke the agent or CLI. It is not a background repository daemon.
- Self-learning is measured and human-gated. Phoenix does not rewrite or adopt its own instructions.
- Use `setup.py` today. The Copilot CLI marketplace/plugin-install path is scaffolded but not yet verified end to end.

## Documentation

- [Developer journey](docs/developer-journey.md): build a project from intent to demonstrated outcome.
- [Autonomous workflows](docs/autonomous-workflows.md): goal, Ralph, state, budgets, and proof.
- [Skill catalog](docs/skills.md): every lifecycle and craft skill.
- [Intent to outcome](docs/intent-to-outcome.md): architecture, research questions, and design rationale.
- [Changelog](CHANGELOG.md): shipped changes by release.
- [Build log](BUILDLOG.md): the full engineering record, including failures and recoveries.

![A phoenix rising from dark rubble in ember orange and cyan light](assets/hero.jpg)

## License

MIT. See [`LICENSE`](LICENSE).

TokenMasterX is owned by the same maintainer and included under its MIT license in
[`vendor/token-master`](vendor/token-master).
