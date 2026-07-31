"""Acceptance tests for mission SLOs (#83).

One rule dominates: **a thin denominator must never pass as green.** AGENTS.md says it about
silent-failure-rate — "always report coverage beside it" — and it generalises. A recovery rate of
1.0 over a single heal is not a good number, it is an absent one, and a metric type that renders it
as 100% is lying by omission.

So these tests mostly attack the zero-denominator and near-zero-denominator cases, because that is
where a metrics layer does real damage.
"""

from __future__ import annotations

from phoenix_learn.events import Event, EventKind, Projection
from phoenix_learn.mission_slo import Rate, compute_slo


def _p(*events: Event) -> Projection:
    return Projection(events=list(events))


def _finished(goal, ok=True, tokens=None, cost=None):
    return Event(
        kind=EventKind.GOAL_FINISHED, mission="m1", goal=goal, ok=ok, tokens=tokens, cost_micros=cost
    )


def _gate(goal, ok=True):
    return Event(kind=EventKind.GATE_EVALUATED, mission="m1", goal=goal, ok=ok)


def _heal(goal, ok):
    return Event(kind=EventKind.HEAL_ATTEMPTED, mission="m1", goal=goal, ok=ok)


def _approval(goal):
    return Event(kind=EventKind.APPROVAL_REQUESTED, mission="m1", goal=goal)


def test_a_rate_with_no_observations_is_unmeasured_not_perfect():
    r = Rate(numerator=0, denominator=0)

    assert r.value is None, "0/0 must not render as 0.0 or 1.0"
    assert not r.is_measured
    assert "unmeasured" in str(r)


def test_a_rate_reports_its_own_denominator():
    r = Rate(numerator=1, denominator=1)

    assert r.value == 1.0
    assert "1/1" in str(r), "a perfect rate over one observation must show the thin denominator"


def test_an_empty_mission_yields_no_fabricated_metrics():
    slo = compute_slo(_p())

    assert slo.proof_coverage.value is None
    assert slo.recovery_rate.value is None
    assert slo.intervention_rate.value is None
    assert slo.total_tokens is None
    assert slo.cost_per_verified_outcome is None


def test_proof_coverage_counts_goals_that_reached_a_gate():
    slo = compute_slo(_p(_finished("g1"), _finished("g2"), _gate("g1")))

    assert slo.proof_coverage.numerator == 1
    assert slo.proof_coverage.denominator == 2
    assert slo.proof_coverage.value == 0.5


def test_a_goal_that_finished_without_a_gate_lowers_proof_coverage():
    """The silent-failure shape: work completed with nothing objective behind it."""
    slo = compute_slo(_p(_finished("g1"), _finished("g2"), _finished("g3"), _gate("g1")))

    assert slo.proof_coverage.value < 0.5
    assert slo.proof_coverage.denominator == 3


def test_terminal_telemetry_coverage_tracks_reported_usage():
    slo = compute_slo(_p(_finished("g1", tokens=100), _finished("g2"), _finished("g3", cost=50)))

    assert slo.terminal_telemetry_coverage.numerator == 2
    assert slo.terminal_telemetry_coverage.denominator == 3


def test_recovery_rate_is_over_heal_attempts_only():
    slo = compute_slo(_p(_finished("g1"), _heal("g1", True), _heal("g1", False)))

    assert slo.recovery_rate.numerator == 1
    assert slo.recovery_rate.denominator == 2


def test_a_single_successful_heal_is_not_a_100_percent_recovery_story():
    slo = compute_slo(_p(_finished("g1"), _heal("g1", True)))

    assert slo.recovery_rate.value == 1.0
    assert slo.recovery_rate.denominator == 1, (
        "the denominator must travel with the value so 1.0 cannot be read as a track record"
    )


def test_intervention_rate_counts_goals_needing_approval():
    slo = compute_slo(_p(_finished("g1"), _finished("g2"), _approval("g1")))

    assert slo.intervention_rate.numerator == 1
    assert slo.intervention_rate.denominator == 2


def test_unreported_usage_is_excluded_rather_than_counted_as_zero():
    slo = compute_slo(_p(_finished("g1", tokens=100, cost=500), _finished("g2")))

    assert slo.total_tokens == 100
    assert slo.total_cost_micros == 500
    assert slo.terminal_telemetry_coverage.denominator == 2, (
        "the unmeasured run still counts against coverage"
    )


def test_a_mission_with_no_measured_cost_reports_none_not_zero():
    slo = compute_slo(_p(_finished("g1"), _finished("g2")))

    assert slo.total_cost_micros is None, "'nobody reported cost' is not 'it was free'"
    assert slo.cost_per_verified_outcome is None


def test_cost_per_verified_outcome_divides_by_verified_only():
    slo = compute_slo(_p(_finished("g1", cost=1000), _finished("g2", ok=False, cost=500)))

    assert slo.verified_outcomes == 1
    assert slo.total_cost_micros == 1500, "failed runs still cost money"
    assert slo.cost_per_verified_outcome == 1500.0


def test_a_fully_failed_mission_does_not_look_maximally_efficient():
    slo = compute_slo(_p(_finished("g1", ok=False, cost=9000)))

    assert slo.verified_outcomes == 0
    assert slo.cost_per_verified_outcome is None, (
        "returning 0.0 here would make a total failure read as free perfection"
    )


def test_tokens_per_verified_outcome_follows_the_same_rule():
    slo = compute_slo(_p(_finished("g1", tokens=300), _finished("g2", ok=False, tokens=100)))

    assert slo.tokens_per_verified_outcome == 400.0
    assert compute_slo(_p(_finished("g1", ok=False, tokens=100))).tokens_per_verified_outcome is None
