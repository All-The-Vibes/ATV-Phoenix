"""The measured-gain adoption gate (ported from goose/tools/sia_h_run.py:decide).

A candidate is ADOPT_ELIGIBLE only when, on the held-out PRIVATE split, it clears every bar:
  * enough evidence:        private_n >= ADOPT_MIN_N
  * a real margin:          (sel_acc - gen0_acc) >= ADOPT_MARGIN  AND
                            (sel_correct - gen0_correct) >= ADOPT_MIN_NET
  * does no harm:           zero right->wrong regressions
  * strictly better:        sel_acc > gen0_acc
Anti-gaming hits short-circuit to REJECT_GAMING_DETECTED; thin evidence -> EXPERIMENTAL_SMOKE_TEST;
anything else -> REJECT. These thresholds match the live Goose loop's standard.

`decide()` assumes cheap, numerous, independent trials, which is what a prompt fixture is.
`decide_episodic()` below covers the other shape: few, expensive, high-variance episodes. The two
rules stay separate on purpose (issue #184).
"""
from __future__ import annotations

ADOPT_MIN_N = 20      # held-out PRIVATE rows required before any auto-adoption
ADOPT_MARGIN = 0.10   # +10pp accuracy on PRIVATE
ADOPT_MIN_NET = 2     # +2 net newly-correct rows on PRIVATE

EPISODIC_MIN_RUNS = 3  # the smallest sample with a median worth beating


def transitions(gen0_results, sel_results):
    """Count per-row outcome moves from baseline (gen0) to the selected candidate.

    Each results list is [{"intent": str, "ok": bool}, ...]. Rows are matched by intent;
    a row absent from gen0 is treated as previously wrong.
    """
    g0 = {r["intent"]: bool(r["ok"]) for r in gen0_results}
    right_to_right = right_to_wrong = wrong_to_right = 0
    for r in sel_results:
        was = g0.get(r["intent"], False)
        now = bool(r["ok"])
        if was and now:
            right_to_right += 1
        elif was and not now:
            right_to_wrong += 1
        elif now and not was:
            wrong_to_right += 1
    return {
        "right_to_right": right_to_right,
        "right_to_wrong": right_to_wrong,
        "wrong_to_right": wrong_to_right,
    }


def decide(
    *,
    gen0_priv_acc: float,
    sel_priv_acc: float,
    sel_priv_correct: int,
    gen0_priv_correct: int,
    trans: dict,
    private_n: int,
    gaming_hits,
):
    """Return the adoption verdict for a candidate measured on the PRIVATE split."""
    if gaming_hits:
        return "REJECT_GAMING_DETECTED"
    if private_n < ADOPT_MIN_N:
        return "EXPERIMENTAL_SMOKE_TEST"

    margin = round(sel_priv_acc - gen0_priv_acc, 4)
    net = sel_priv_correct - gen0_priv_correct
    if (
        margin >= ADOPT_MARGIN
        and net >= ADOPT_MIN_NET
        and trans.get("right_to_wrong", 0) == 0
        and sel_priv_acc > gen0_priv_acc
    ):
        return "ADOPT_ELIGIBLE"
    return "REJECT"


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def episodic_summary(*, baseline_runs, candidate_runs):
    """The numbers an episodic verdict is made on, without the verdict.

    Kept separate from `decide_episodic` so a caller cannot read the numbers and quietly
    substitute its own judgement for the gate's.
    """
    baseline = list(baseline_runs)
    candidate = list(candidate_runs)
    baseline_median = _median(baseline)
    baseline_worst = min(baseline) if baseline else None
    candidate_worst = min(candidate) if candidate else None
    dominates = (
        baseline_median is not None
        and candidate_worst is not None
        and candidate_worst > baseline_median
    )
    return {
        "baseline_n": len(baseline),
        "candidate_n": len(candidate),
        "baseline_median": baseline_median,
        "baseline_worst": baseline_worst,
        "candidate_worst": candidate_worst,
        "dominates_lower_tail": dominates,
    }


def decide_episodic(*, baseline_runs, candidate_runs, gaming_hits):
    """Adoption verdict for few, expensive, high-variance runs.

    The bar is stochastic dominance on the lower tail: the candidate's WORST run must beat the
    baseline's MEDIAN. That refuses a single lucky run by construction, which is the failure
    this rule exists to stop. On sb26 a change was adopted on one green run at RHAE 3.11 percent
    and the confirmation run on identical code returned 0.13 percent.

    The issue also asks that no candidate run be worse than the baseline's worst. That bar is
    implied rather than coded: a median is never below its own minimum, so a candidate whose
    worst run beats the baseline median already beats the baseline worst. Writing it as a
    second branch would ship a condition that can never fire on its own, and an unreachable
    guard reads as protection nobody has.

    Both samples must reach EPISODIC_MIN_RUNS. A one-run baseline has no median worth beating,
    and a verdict over zero runs is unmeasured rather than clean.
    """
    if gaming_hits:
        return "REJECT_GAMING_DETECTED"

    summary = episodic_summary(baseline_runs=baseline_runs, candidate_runs=candidate_runs)
    if summary["baseline_n"] < EPISODIC_MIN_RUNS or summary["candidate_n"] < EPISODIC_MIN_RUNS:
        return "EXPERIMENTAL_SMOKE_TEST"
    if summary["dominates_lower_tail"]:
        return "ADOPT_ELIGIBLE"
    return "REJECT"
