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


def _score_and_seed(run):
    """Accept a seeded run mapping, or a bare number whose seed is unknown.

    A bare number is not rejected here. It is carried through with `seed=None` so the caller
    gets told which sample could not name its seed, rather than a type error (issue #185).
    """
    if isinstance(run, dict):
        return float(run["score"]), run.get("seed")
    return float(run), None


def _reproducibility(baseline, candidate):
    """(ok, reason). A sample is reproducible when every run names a seed and no seed
    disagrees with itself.

    `seed` was probed against the deployment on 2026-08-08 and reproduces byte-identical
    output, while `temperature=0` and `top_p` are both rejected. So one seed producing two
    different scores means the determinism this gate assumed does not hold for that run, and
    the sample cannot be re-run to check.
    """
    for label, sample in (("baseline", baseline), ("candidate", candidate)):
        by_seed = {}
        for score, seed in sample:
            if seed is None:
                return False, "a %s run does not name its seed, so it cannot be re-run" % label
            if seed in by_seed and by_seed[seed] != score:
                return False, (
                    "%s seed %r produced %s and %s, so it does not reproduce"
                    % (label, seed, by_seed[seed], score))
            by_seed[seed] = score
    return True, None


def episodic_summary(*, baseline_runs, candidate_runs):
    """The numbers an episodic verdict is made on, without the verdict.

    Kept separate from `decide_episodic` so a caller cannot read the numbers and quietly
    substitute its own judgement for the gate's.
    """
    baseline = [_score_and_seed(r) for r in baseline_runs]
    candidate = [_score_and_seed(r) for r in candidate_runs]
    baseline_scores = [s for s, _ in baseline]
    candidate_scores = [s for s, _ in candidate]
    baseline_seeds = [seed for _, seed in baseline]
    candidate_seeds = [seed for _, seed in candidate]

    baseline_median = _median(baseline_scores)
    baseline_worst = min(baseline_scores) if baseline_scores else None
    candidate_worst = min(candidate_scores) if candidate_scores else None
    dominates = (
        baseline_median is not None
        and candidate_worst is not None
        and candidate_worst > baseline_median
    )
    reproducible, reason = _reproducibility(baseline, candidate)
    return {
        "baseline_n": len(baseline),
        "candidate_n": len(candidate),
        "baseline_median": baseline_median,
        "baseline_worst": baseline_worst,
        "candidate_worst": candidate_worst,
        "dominates_lower_tail": dominates,
        "baseline_seeds": baseline_seeds,
        "candidate_seeds": candidate_seeds,
        "distinct_baseline_seeds": len({s for s in baseline_seeds if s is not None}),
        "distinct_candidate_seeds": len({s for s in candidate_seeds if s is not None}),
        "reproducible": reproducible,
        "unreproducible_reason": reason,
    }


def decide_episodic(*, baseline_runs, candidate_runs, gaming_hits):
    """Adoption verdict for few, expensive, high-variance runs.

    A run is `{"score": float, "seed": hashable}`, or a bare number whose seed is unknown.

    The bar is stochastic dominance on the lower tail: the candidate's WORST run must beat the
    baseline's MEDIAN. That refuses a single lucky run by construction, which is the failure
    this rule exists to stop. On sb26 a change was adopted on one green run at RHAE 3.11 percent
    and the confirmation run on identical code returned 0.13 percent.

    Seeds are part of the evidence (issue #185). A run that cannot name its seed cannot be
    re-run, so the verdict is REJECT_UNREPRODUCIBLE rather than green, and that objection
    outranks thin evidence because a sample nobody can reproduce is a worse problem than a
    sample that is small. Evidence is counted in DISTINCT seeds, so three runs at seed 42 are
    one observation rather than three.

    The issue also asks that no candidate run be worse than the baseline's worst. That bar is
    implied rather than coded: a median is never below its own minimum, so a candidate whose
    worst run beats the baseline median already beats the baseline worst. Writing it as a
    second branch would ship a condition that can never fire on its own, and an unreachable
    guard reads as protection nobody has.

    An empty sample is EXPERIMENTAL_SMOKE_TEST rather than clean, and carries no seed to
    object to, so emptiness is judged before reproducibility.
    """
    if gaming_hits:
        return "REJECT_GAMING_DETECTED"

    summary = episodic_summary(baseline_runs=baseline_runs, candidate_runs=candidate_runs)
    if summary["baseline_n"] == 0 or summary["candidate_n"] == 0:
        return "EXPERIMENTAL_SMOKE_TEST"
    if not summary["reproducible"]:
        return "REJECT_UNREPRODUCIBLE"
    if (
        summary["distinct_baseline_seeds"] < EPISODIC_MIN_RUNS
        or summary["distinct_candidate_seeds"] < EPISODIC_MIN_RUNS
    ):
        return "EXPERIMENTAL_SMOKE_TEST"
    if summary["dominates_lower_tail"]:
        return "ADOPT_ELIGIBLE"
    return "REJECT"
