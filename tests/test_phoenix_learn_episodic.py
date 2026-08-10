"""The episodic adoption gate, with seeds as part of the evidence. (issues #184, #185)

`decide()` needs `ADOPT_MIN_N = 20` held-out rows. One ARC-AGI-3 run costs 4 to 10 minutes of
real API spend, so clearing that bar is 2 to 3 hours of wall clock per decision, and in practice
`decide()` returned `EXPERIMENTAL_SMOKE_TEST` on every ARC call and gated nothing.

The failure that rule could not prevent is measured: a change was adopted on a single green run at
RHAE 3.11 percent, and the confirmation run on identical code came back at 0.13 percent. Level-1
action counts on identical config were 69, 17 and 83.

That variance was the model's sampling and it was pinnable the whole time. Probed against the
deployment on 2026-08-08: `temperature=0` and `top_p` are both rejected with HTTP 400, and `seed`
is honoured and reproduces byte-identical output. `arc_agi.Arcade.make()` already defaults to
`seed=0`. So a run that cannot name its seed cannot be re-run, and #185 says such a check is
reported as unreproducible rather than as green.

These tests live outside `phoenix_learn/gate.py`, so the gate cannot be satisfied by editing the
thing under test.
"""
from __future__ import annotations

import pytest

from phoenix_learn.gate import (
    EPISODIC_MIN_RUNS,
    decide,
    decide_episodic,
    episodic_summary,
)

# The measured sb26 numbers: one lucky run over a baseline that mostly does better.
LUCKY_CANDIDATE = [
    {"score": 0.0013, "seed": 7},
    {"score": 0.0311, "seed": 42},
    {"score": 0.0020, "seed": 99},
]
STEADY_BASELINE = [
    {"score": 0.0180, "seed": 7},
    {"score": 0.0192, "seed": 42},
    {"score": 0.0205, "seed": 99},
]


def _seeded(scores, seeds=None):
    seeds = seeds or list(range(len(scores)))
    return [{"score": s, "seed": seed} for s, seed in zip(scores, seeds)]


def _ep(baseline, candidate, gaming_hits=()):
    return decide_episodic(
        baseline_runs=baseline, candidate_runs=candidate, gaming_hits=gaming_hits)


# --- the failure this gate exists to stop ------------------------------------------


def test_a_single_lucky_run_does_not_carry_the_decision():
    """3.11 percent once, 0.13 and 0.20 the other two times, against a steadier baseline."""
    assert _ep(STEADY_BASELINE, LUCKY_CANDIDATE) == "REJECT"


def test_the_same_candidate_would_pass_if_only_its_best_run_were_read():
    """States the trap plainly: max beats the baseline, the distribution does not."""
    assert max(r["score"] for r in LUCKY_CANDIDATE) > max(r["score"] for r in STEADY_BASELINE)
    assert _ep(STEADY_BASELINE, LUCKY_CANDIDATE) == "REJECT"


def test_a_candidate_that_dominates_the_lower_tail_is_adopted():
    assert _ep(_seeded([0.10, 0.20, 0.30]), _seeded([0.25, 0.40, 0.45])) == "ADOPT_ELIGIBLE"


def test_the_worst_candidate_run_must_beat_the_baseline_median():
    base = _seeded([0.10, 0.20, 0.30])
    assert _ep(base, _seeded([0.19, 0.90, 0.95])) == "REJECT"
    assert _ep(base, _seeded([0.21, 0.90, 0.95])) == "ADOPT_ELIGIBLE"


def test_beating_the_median_is_strict():
    """A tie is not a win. Equal distributions must not adopt."""
    assert _ep(_seeded([0.10, 0.20, 0.30]), _seeded([0.20, 0.50, 0.60])) == "REJECT"


# --- seeds are part of the evidence ------------------------------------------------


def test_a_run_that_cannot_name_its_seed_is_not_green():
    """The #185 rule. A bare score cannot be re-run, so it cannot be adopted on."""
    assert decide_episodic(
        baseline_runs=[0.10, 0.20, 0.30],
        candidate_runs=[0.25, 0.40, 0.45],
        gaming_hits=[],
    ) == "REJECT_UNREPRODUCIBLE"


def test_one_unseeded_run_is_enough_to_taint_the_sample():
    candidate = _seeded([0.25, 0.40, 0.45])
    candidate[1] = 0.40  # drops the seed on a single run

    assert _ep(_seeded([0.10, 0.20, 0.30]), candidate) == "REJECT_UNREPRODUCIBLE"


def test_an_unseeded_baseline_taints_it_too():
    assert _ep([0.10, 0.20, 0.30], _seeded([0.25, 0.40, 0.45])) == "REJECT_UNREPRODUCIBLE"


def test_repeats_of_one_seed_are_not_three_observations():
    """N distinct seeds, not N repeats of one. Three runs at seed 42 is one observation."""
    same = [{"score": 0.90, "seed": 42} for _ in range(3)]

    assert _ep(_seeded([0.10, 0.20, 0.30]), same) == "EXPERIMENTAL_SMOKE_TEST"


def test_two_distinct_seeds_padded_with_a_repeat_is_still_two():
    candidate = [
        {"score": 0.90, "seed": 1},
        {"score": 0.95, "seed": 2},
        {"score": 0.90, "seed": 1},
    ]

    assert _ep(_seeded([0.10, 0.20, 0.30]), candidate) == "EXPERIMENTAL_SMOKE_TEST"


def test_one_seed_producing_two_different_scores_is_unreproducible():
    """The determinism this gate assumed. `seed=42` reproduced byte-identical output when
    probed, so two different scores under one seed means the assumption is false here."""
    contradictory = [
        {"score": 0.90, "seed": 42},
        {"score": 0.55, "seed": 42},
        {"score": 0.95, "seed": 2},
        {"score": 0.96, "seed": 3},
    ]

    assert _ep(_seeded([0.10, 0.20, 0.30]), contradictory) == "REJECT_UNREPRODUCIBLE"


def test_the_same_seed_repeating_the_same_score_is_fine():
    """A faithful repeat is redundant, not contradictory. It just does not add an observation."""
    honest = [
        {"score": 0.90, "seed": 1},
        {"score": 0.90, "seed": 1},
        {"score": 0.95, "seed": 2},
        {"score": 0.96, "seed": 3},
    ]

    assert _ep(_seeded([0.10, 0.20, 0.30]), honest) == "ADOPT_ELIGIBLE"


def test_seed_zero_is_a_seed():
    """`Arcade.make()` defaults to seed=0, so a falsy seed must not read as absent."""
    candidate = [
        {"score": 0.25, "seed": 0},
        {"score": 0.40, "seed": 1},
        {"score": 0.45, "seed": 2},
    ]

    assert _ep(_seeded([0.10, 0.20, 0.30], seeds=[0, 1, 2]), candidate) == "ADOPT_ELIGIBLE"


def test_unreproducible_outranks_thin_evidence():
    """A sample that cannot be re-run is a stronger objection than a sample that is small."""
    assert decide_episodic(
        baseline_runs=[0.10, 0.20], candidate_runs=[0.90, 0.95], gaming_hits=[],
    ) == "REJECT_UNREPRODUCIBLE"


def test_gaming_still_outranks_everything():
    assert _ep(_seeded([0.10, 0.20, 0.30]), _seeded([0.90, 0.95, 0.99]),
               gaming_hits=["copied the answer"]) == "REJECT_GAMING_DETECTED"


# --- thin and empty evidence -------------------------------------------------------


def test_the_minimum_run_count_matches_the_shape_this_rule_is_for():
    assert 3 <= EPISODIC_MIN_RUNS <= 5


def test_a_uniformly_better_candidate_still_needs_enough_seeds():
    assert _ep(_seeded([0.10, 0.20, 0.30]), _seeded([0.90, 0.95])) == "EXPERIMENTAL_SMOKE_TEST"


def test_no_runs_at_all_is_unmeasured_not_adopted():
    assert _ep([], []) == "EXPERIMENTAL_SMOKE_TEST"
    assert _ep(_seeded([0.1, 0.2, 0.3]), []) == "EXPERIMENTAL_SMOKE_TEST"
    assert _ep([], _seeded([0.9, 0.9, 0.9])) == "EXPERIMENTAL_SMOKE_TEST"


def test_a_thin_baseline_cannot_be_cleared_by_a_fat_candidate():
    assert _ep(_seeded([0.10]), _seeded([0.90, 0.95, 0.99])) == "EXPERIMENTAL_SMOKE_TEST"


# --- the summary carries the numbers the verdict was made on ------------------------


def test_the_summary_reports_what_the_decision_used():
    s = episodic_summary(
        baseline_runs=_seeded([0.10, 0.20, 0.30]), candidate_runs=_seeded([0.25, 0.40, 0.45]))

    assert s["baseline_median"] == pytest.approx(0.20)
    assert s["baseline_worst"] == pytest.approx(0.10)
    assert s["candidate_worst"] == pytest.approx(0.25)
    assert s["baseline_n"] == 3
    assert s["candidate_n"] == 3
    assert s["dominates_lower_tail"] is True


def test_the_summary_reports_the_seeds_it_ran_under():
    s = episodic_summary(
        baseline_runs=_seeded([0.10, 0.20, 0.30], seeds=[1, 2, 3]),
        candidate_runs=_seeded([0.25, 0.40, 0.45], seeds=[1, 2, 3]))

    assert s["baseline_seeds"] == [1, 2, 3]
    assert s["candidate_seeds"] == [1, 2, 3]
    assert s["distinct_baseline_seeds"] == 3
    assert s["distinct_candidate_seeds"] == 3
    assert s["reproducible"] is True
    assert s["unreproducible_reason"] is None


def test_the_summary_names_why_a_sample_is_unreproducible():
    s = episodic_summary(baseline_runs=_seeded([0.1, 0.2, 0.3]), candidate_runs=[0.9, 0.9, 0.9])

    assert s["reproducible"] is False
    assert "seed" in s["unreproducible_reason"]


def test_the_summary_names_the_contradicting_seed():
    s = episodic_summary(
        baseline_runs=_seeded([0.1, 0.2, 0.3]),
        candidate_runs=[{"score": 0.9, "seed": 42}, {"score": 0.5, "seed": 42},
                        {"score": 0.95, "seed": 2}])

    assert s["reproducible"] is False
    assert "42" in s["unreproducible_reason"]


def test_the_summary_is_honest_about_an_empty_sample():
    s = episodic_summary(baseline_runs=[], candidate_runs=[])

    assert s["baseline_median"] is None
    assert s["baseline_worst"] is None
    assert s["candidate_worst"] is None
    assert s["dominates_lower_tail"] is False


def test_the_median_is_a_real_median_on_an_even_sample():
    s = episodic_summary(
        baseline_runs=_seeded([0.10, 0.20, 0.30, 0.40]), candidate_runs=_seeded([0.9] * 3))

    assert s["baseline_median"] == pytest.approx(0.25)


def test_the_summary_does_not_decide():
    """A summary that returned a verdict would let a caller read the numbers and ignore it."""
    assert "verdict" not in episodic_summary(
        baseline_runs=_seeded([0.1, 0.2, 0.3]), candidate_runs=_seeded([0.9, 0.9, 0.9]))


# --- the redundancy is recorded rather than shipped as dead code --------------------


def test_no_candidate_run_can_be_worse_than_the_baseline_worst_once_the_tail_bar_holds():
    """A median is never below its own minimum, so the issue's second bar is implied by the
    first and is not coded as a branch that could never fire."""
    baseline = _seeded([0.10, 0.20, 0.30])
    candidate = _seeded([0.25, 0.40, 0.45])
    s = episodic_summary(baseline_runs=baseline, candidate_runs=candidate)

    assert s["dominates_lower_tail"] is True
    assert all(r["score"] > s["baseline_worst"] for r in candidate)


# --- the row rule is untouched -----------------------------------------------------


def test_the_row_gate_still_behaves_exactly_as_before():
    assert decide(
        gen0_priv_acc=0.50, sel_priv_acc=0.70, sel_priv_correct=14, gen0_priv_correct=10,
        trans={"right_to_wrong": 0}, private_n=20, gaming_hits=[],
    ) == "ADOPT_ELIGIBLE"
    assert decide(
        gen0_priv_acc=0.50, sel_priv_acc=0.90, sel_priv_correct=9, gen0_priv_correct=5,
        trans={"right_to_wrong": 0}, private_n=10, gaming_hits=[],
    ) == "EXPERIMENTAL_SMOKE_TEST"


def test_the_episodic_rule_does_not_borrow_the_row_threshold():
    from phoenix_learn.gate import ADOPT_MIN_N

    assert EPISODIC_MIN_RUNS < ADOPT_MIN_N
    assert _ep(_seeded([0.10, 0.20, 0.30]), _seeded([0.25, 0.40, 0.45])) == "ADOPT_ELIGIBLE"


def test_every_verdict_branch_is_reachable():
    verdicts = {
        _ep(_seeded([0.1, 0.2, 0.3]), _seeded([0.25, 0.4, 0.45])),
        _ep(_seeded([0.1, 0.2, 0.3]), _seeded([0.05, 0.4, 0.45])),
        _ep([], []),
        _ep(_seeded([0.1, 0.2, 0.3]), _seeded([0.9, 0.9, 0.9]), gaming_hits=["x"]),
        _ep([0.1, 0.2, 0.3], [0.9, 0.9, 0.9]),
    }

    assert verdicts == {
        "ADOPT_ELIGIBLE",
        "REJECT",
        "EXPERIMENTAL_SMOKE_TEST",
        "REJECT_GAMING_DETECTED",
        "REJECT_UNREPRODUCIBLE",
    }
