"""The episodic adoption gate: few, expensive, high-variance runs. (issue #184)

`decide()` needs `ADOPT_MIN_N = 20` held-out rows. One ARC-AGI-3 run costs 4 to 10 minutes of
real API spend, so clearing that bar is 2 to 3 hours of wall clock per decision, and in practice
`decide()` returned `EXPERIMENTAL_SMOKE_TEST` on every ARC call and gated nothing.

The failure that rule could not prevent is measured: a change was adopted on a single green run at
RHAE 3.11 percent, and the confirmation run on identical code came back at 0.13 percent. Level-1
action counts on identical config were 69, 17 and 83. The variance is the signal, so the episodic
rule compares distributions instead of counting rows.

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

# The measured sb26 numbers from the issue: one lucky run over a baseline that mostly does better.
LUCKY_CANDIDATE = [0.0013, 0.0311, 0.0020]
STEADY_BASELINE = [0.0180, 0.0192, 0.0205]


def _ep(baseline, candidate, gaming_hits=()):
    return decide_episodic(
        baseline_runs=baseline, candidate_runs=candidate, gaming_hits=gaming_hits)


# --- the failure this gate exists to stop ------------------------------------------


def test_a_single_lucky_run_does_not_carry_the_decision():
    """3.11 percent once, 0.13 and 0.20 the other two times, against a steadier baseline."""
    assert _ep(STEADY_BASELINE, LUCKY_CANDIDATE) == "REJECT"


def test_the_same_candidate_would_pass_if_only_its_best_run_were_read():
    """States the trap plainly: max beats the baseline, the distribution does not."""
    assert max(LUCKY_CANDIDATE) > max(STEADY_BASELINE)
    assert _ep(STEADY_BASELINE, LUCKY_CANDIDATE) == "REJECT"


def test_a_candidate_that_dominates_the_lower_tail_is_adopted():
    assert _ep([0.10, 0.20, 0.30], [0.25, 0.40, 0.45]) == "ADOPT_ELIGIBLE"


def test_the_worst_candidate_run_must_beat_the_baseline_median():
    # Candidate worst 0.19 sits just under the baseline median 0.20.
    assert _ep([0.10, 0.20, 0.30], [0.19, 0.90, 0.95]) == "REJECT"
    # Lift that one run over the median and the verdict flips.
    assert _ep([0.10, 0.20, 0.30], [0.21, 0.90, 0.95]) == "ADOPT_ELIGIBLE"


def test_beating_the_median_is_strict():
    """A tie is not a win. Equal distributions must not adopt."""
    assert _ep([0.10, 0.20, 0.30], [0.20, 0.50, 0.60]) == "REJECT"


def test_a_uniformly_better_candidate_still_needs_enough_runs():
    assert _ep([0.10, 0.20, 0.30], [0.90, 0.95]) == "EXPERIMENTAL_SMOKE_TEST"


# --- thin and empty evidence -------------------------------------------------------


def test_the_minimum_run_count_matches_the_shape_this_rule_is_for():
    assert 3 <= EPISODIC_MIN_RUNS <= 5


def test_no_runs_at_all_is_unmeasured_not_adopted():
    assert _ep([], []) == "EXPERIMENTAL_SMOKE_TEST"
    assert _ep([0.1, 0.2, 0.3], []) == "EXPERIMENTAL_SMOKE_TEST"
    assert _ep([], [0.9, 0.9, 0.9]) == "EXPERIMENTAL_SMOKE_TEST"


def test_a_thin_baseline_cannot_be_cleared_by_a_fat_candidate():
    """An empty or one-run baseline has no median worth beating."""
    assert _ep([0.10], [0.90, 0.95, 0.99]) == "EXPERIMENTAL_SMOKE_TEST"


def test_gaming_short_circuits_before_any_arithmetic():
    assert _ep([0.10, 0.20, 0.30], [0.90, 0.95, 0.99], gaming_hits=["copied the answer"]) == \
        "REJECT_GAMING_DETECTED"


# --- the summary carries the numbers the verdict was made on ------------------------


def test_the_summary_reports_what_the_decision_used():
    s = episodic_summary(baseline_runs=[0.10, 0.20, 0.30], candidate_runs=[0.25, 0.40, 0.45])

    assert s["baseline_median"] == pytest.approx(0.20)
    assert s["baseline_worst"] == pytest.approx(0.10)
    assert s["candidate_worst"] == pytest.approx(0.25)
    assert s["baseline_n"] == 3
    assert s["candidate_n"] == 3
    assert s["dominates_lower_tail"] is True


def test_the_summary_is_honest_about_an_empty_sample():
    s = episodic_summary(baseline_runs=[], candidate_runs=[])

    assert s["baseline_median"] is None
    assert s["baseline_worst"] is None
    assert s["candidate_worst"] is None
    assert s["dominates_lower_tail"] is False


def test_the_median_is_a_real_median_on_an_even_sample():
    s = episodic_summary(baseline_runs=[0.10, 0.20, 0.30, 0.40], candidate_runs=[0.9] * 3)

    assert s["baseline_median"] == pytest.approx(0.25)


def test_the_summary_does_not_decide():
    """A summary that returned a verdict would let a caller read the numbers and ignore it."""
    assert "verdict" not in episodic_summary(
        baseline_runs=[0.1, 0.2, 0.3], candidate_runs=[0.9, 0.9, 0.9])


# --- the redundancy is recorded rather than shipped as dead code --------------------


def test_no_candidate_run_can_be_worse_than_the_baseline_worst_once_the_tail_bar_holds():
    """The issue asks for two bars. The second is implied by the first, so it is not coded
    as a second branch that could never fire.

    A median is never below its own minimum, so candidate_worst > baseline_median implies
    candidate_worst > baseline_worst, and every other candidate run is at least the worst.
    """
    baseline = [0.10, 0.20, 0.30]
    candidate = [0.25, 0.40, 0.45]
    s = episodic_summary(baseline_runs=baseline, candidate_runs=candidate)

    assert s["dominates_lower_tail"] is True
    assert min(candidate) > s["baseline_worst"]
    assert all(run > s["baseline_worst"] for run in candidate)


# --- the row rule is untouched -----------------------------------------------------


def test_the_row_gate_still_behaves_exactly_as_before():
    """`decide()` is for row fixtures and this issue says not to stretch one rule over both."""
    assert decide(
        gen0_priv_acc=0.50, sel_priv_acc=0.70, sel_priv_correct=14, gen0_priv_correct=10,
        trans={"right_to_wrong": 0}, private_n=20, gaming_hits=[],
    ) == "ADOPT_ELIGIBLE"
    assert decide(
        gen0_priv_acc=0.50, sel_priv_acc=0.90, sel_priv_correct=9, gen0_priv_correct=5,
        trans={"right_to_wrong": 0}, private_n=10, gaming_hits=[],
    ) == "EXPERIMENTAL_SMOKE_TEST"


def test_the_episodic_rule_does_not_borrow_the_row_threshold():
    """20 expensive episodes is the bar that made the row rule unusable here."""
    from phoenix_learn.gate import ADOPT_MIN_N

    assert EPISODIC_MIN_RUNS < ADOPT_MIN_N
    assert _ep([0.10, 0.20, 0.30], [0.25, 0.40, 0.45]) == "ADOPT_ELIGIBLE"


def test_both_rules_share_one_verdict_vocabulary():
    verdicts = {
        _ep([0.1, 0.2, 0.3], [0.25, 0.4, 0.45]),
        _ep([0.1, 0.2, 0.3], [0.05, 0.4, 0.45]),
        _ep([], []),
        _ep([0.1, 0.2, 0.3], [0.9, 0.9, 0.9], gaming_hits=["x"]),
    }

    assert verdicts <= {
        "ADOPT_ELIGIBLE", "REJECT", "EXPERIMENTAL_SMOKE_TEST", "REJECT_GAMING_DETECTED"}
    assert len(verdicts) == 4, "each branch must be reachable"
