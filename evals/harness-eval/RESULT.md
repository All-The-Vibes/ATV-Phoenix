# Harness evaluation result

## Evidence and methodology

This is the current-version replication recorded in
[`results/run-manifest.json`](results/run-manifest.json) and
[`results/raw-runs.jsonl`](results/raw-runs.jsonl). The manifest pins the source, build, model,
runner, environment, task set, seeds, and evaluator hashes. The manifest
`pins.raw_jsonl_hash` value
`dde7a938a3f77dcb2d8cb6f69992e1d04858db0fcc77c6bfd219044dae4f8950` is the SHA-256 of
the run-time generated `raw-runs.jsonl` artifact bytes in the pinned Windows environment. The
committed Git blob is LF-normalized and has SHA-256
`bd77be8b8dfdcda8b3c5bc1842880661d0ca5e3e7f8ff8578891853849160223`. Git newline
normalization changed the generated CRLF line endings to LF when the file was committed, so these
hashes are expected to be distinct.

The preregistered design ran nine tasks at five fixed seeds, once per task/seed/arm (45 paired
units and 90 runs). Each pair used the same task and seed, isolated arm state, and
deterministically counterbalanced order. Objective pass required both evaluator-only Level 1 and
Level 2 checks. All runs claimed completion, cost one pinned unit, and were non-mock runs.

Uncertainty is the preregistered 95% paired bootstrap over task/seed pairs: 10,000 resamples with
fixed analysis seed 32452843. Intervals below are percentile intervals; differences are Phoenix
minus control.

## Objective results

| Arm | Objective passes | Pass rate (95% CI) | Silent failures | Silent-failure rate (95% CI) | Cost / verified outcome (95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Phoenix | 38 / 45 | 84.4% (73.3%–93.3%) | 7 / 45 | 15.6% (6.7%–26.7%) | 1.18 (1.07–1.36) |
| Control | 34 / 45 | 75.6% (62.2%–86.7%) | 11 / 45 | 24.4% (13.3%–37.8%) | 1.32 (1.15–1.61) |

The paired pass-rate difference is +8.9 percentage points (95% CI −4.4 to +22.2); the
silent-failure-rate difference is −8.9 points (−22.2 to +4.4); and the cost difference is −0.14
pinned units (−0.40 to +0.07). Pair outcomes were 31 both pass, 7 Phoenix only, 3 control only,
and 4 neither. These are objective counts, not a subjective ranking.

## External-comparison evidence boundary

The designated committed benchmark artifacts do not archive the external comparison. This report
therefore cannot verify whether that comparison pinned a Phoenix version, used N=1, objectively
tied, or contained a score-display typo. No source-specific correction is published. In
particular, no score-display correction is published because no archived source was available to
verify it.

The only applicable statements are general methodological rules:

- An unpinned comparison is not reproducible.
- An objective tie cannot be converted into an objective winner by subjective ordering.
- N=1 cannot support comparative ranking.

## Limitations

- Coverage is nine small tasks and five fixed seeds, not the broader task population.
- There is one run per task/seed/arm. Five seeds provide repeated paired observations, but not
  repeated executions of each identical task/seed/arm condition.
- The manifest records resource-limit enforcement as `none`; Windows job objects were not
  configured, while process memory and CPU time were OS-managed. Cost units therefore are not
  independently enforced resource measurements.
- The bootstrap treats 45 task/seed pairs as resampling units; seeds within a task may not be
  independent, and only nine distinct tasks constrain generalization.
- The confidence intervals include zero for every paired arm difference. The observed point
  differences therefore do not establish a comparative ranking.
- Subjective assessment was not collected here and, under the protocol, would be secondary
  diagnostic interpretation only.
