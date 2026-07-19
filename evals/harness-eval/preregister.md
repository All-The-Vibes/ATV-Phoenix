# Phoenix harness evaluation preregistration

## Status and scope

This document preregisters a prospective, paired Phoenix-versus-control evaluation. **No benchmark
run has occurred**, this directory contains no results, and it supports no performance claim. The
machine-readable contract is [`protocol.json`](protocol.json).

Every value marked `preregistration_placeholder` is a deterministic preregistration value, not a
measured artifact. Before the first benchmark run, the future runner must replace each such value
with its run-specific immutable value and pass preflight validation. It must then freeze the
complete protocol and manifest for the duration of the evaluation. Placeholder-bearing protocols
must remain `execution_status: not_run` and cannot be presented as completed evidence.

## Immutable pins

The preflight manifest pins:

- Phoenix source commit and build stamp;
- exact model ID and runner version;
- SHA-256 environment-manifest and ordered task-set hashes;
- the preregistered seeds;
- the Level-1 sealed verifier hash; and
- the Level-2 adversarial verifier hash.

The environment manifest records the runner operating system, architecture, installed runtime and
dependency versions, relevant resource limits, and execution-policy settings without secrets or
personal data. The task-set digest is over a canonical, ordered task manifest. The runner refuses
to start if any required placeholder remains and refuses to continue if a pin changes.

## Paired execution design

The experimental arms are `phoenix` and `control`. Each pair uses the **same task and seed**, with
exactly one isolated run per arm. Arm order is deterministically counterbalanced from task ID and
seed. Incomplete pairs are excluded from paired analysis and reported as attrition; they are not
silently replaced with unpaired observations.

`min_repetitions` is 5. Each task uses all five fixed seeds in `protocol.json`, yielding five paired
repetitions per task. Arm state, workspaces, and caches are isolated so one arm cannot affect the
other.

## Mock boundary

Mocks are explicitly classified `mechanics_only`. They may test runner wiring, parsing, pairing,
and metric calculations. Mock runs are **not performance evidence**, are excluded from metrics, and
cannot support comparisons or product claims.

## Evaluator separation

Agent-visible checks are limited to public task acceptance checks and checks declared by repository
instructions. Their identities are recorded separately from evaluator-only checks.

Level-1 sealed checks are evaluator-only objective checks whose contents are unavailable to either
arm. Level-2 adversarial checks are also evaluator-only and probe likely superficial, overfit, or
shortcut solutions. Only verifier hashes are pinned in the protocol; verifier contents, expected
outputs, and evaluator feedback are not exposed to the agent before or during a run. Evaluator
feedback is recorded only after the arm has terminated.

## Outcomes and analysis

The primary output is a paired objective metric report, not a quality ranking:

- **Objective pass:** numerator = eligible completed runs passing all required sealed and
  adversarial checks; denominator = all eligible completed runs.
- **Silent-failure numerator:** runs that claim completion but fail any required evaluator check.
- **Silent-failure denominator:** all runs that claim completion. The raw numerator and denominator
  are always reported beside the rate.
- **Cost per verified outcome:** total cost in the preregistered pinned cost units divided by the
  objective-pass count. A zero pass count is reported as undefined with both raw components.
- **Confidence intervals:** two-sided 95% paired-bootstrap intervals with 10,000 resamples at the
  `(task_id, seed)` pair level, using the fixed analysis seed in `protocol.json`. Intervals cover
  arm rates, costs, and paired arm differences.

A ranked subjective leaderboard is not the primary output. Any subjective review is a secondary
diagnostic, is reported separately, and cannot override objective verifier outcomes.

## Evidence rule

Completed evidence requires the frozen immutable pin manifest, paired raw records, sealed and
adversarial evaluator records, and reproducible metric-computation records. Until those artifacts
exist, `benchmark_results` stays empty and `performance_claims_allowed` stays false. This
preregistration intentionally reports no score, winner, improvement, or completed run.
