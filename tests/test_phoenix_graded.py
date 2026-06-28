"""Tests for phoenix_learn.graded — the graded/Bayesian acceptance gate (issue #18).

The binary phoenix_sense gate (red/green on an exit code, file hash, or regex) is the
right tool for *deterministic* code. It is too brittle for *non-deterministic generative
output* (audio/video/image/text), where a single artifact is rarely all-right or
all-wrong. `graded` scores an artifact against a weighted rubric, folds the per-criterion
scores into a conjugate Beta posterior over latent quality, and returns ACCEPT / REVIEW /
REJECT based on whether a credible interval clears the acceptance threshold tau — so the
loop can say "confidently good", "confidently not good", or honestly "borderline, get more
evidence" instead of being forced into a brittle pass/fail.

These tests are deterministic, offline, zero-LLM. They pin the decision logic, the
critical-floor short-circuit (the honesty core: a critical safety/PII miss can never be
averaged away by high aesthetic scores), and the dependency-free Beta math. This is the
phoenix_sense acceptance check for #18.
"""
import math

import pytest

import phoenix_learn as pl
from phoenix_learn.graded import grade, is_accept, ACCEPT, REVIEW, REJECT
from phoenix_learn import graded as G


# --- decision logic -------------------------------------------------------------------

def test_confident_high_quality_accepts():
    # Several criteria all scoring well above tau -> credible lower bound clears tau.
    crit = [{"name": f"c{i}", "score": 0.96} for i in range(5)]
    v = grade(crit, tau=0.70)
    assert v["decision"] == ACCEPT
    assert is_accept(v) is True
    assert v["ci"][0] >= 0.70


def test_confident_low_quality_rejects():
    # All criteria well below tau -> credible upper bound is below tau.
    crit = [{"name": f"c{i}", "score": 0.15} for i in range(5)]
    v = grade(crit, tau=0.70)
    assert v["decision"] == REJECT
    assert v["ci"][1] < 0.70


def test_borderline_returns_review_not_binary():
    # Thin evidence straddling tau -> the gate must NOT force a pass/fail; it asks for more.
    crit = [{"name": "a", "score": 0.75}, {"name": "b", "score": 0.74},
            {"name": "c", "score": 0.73}]
    v = grade(crit, tau=0.70)
    assert v["decision"] == REVIEW
    assert v["ci"][0] < 0.70 < v["ci"][1]


def test_critical_failure_rejects_despite_high_aggregate():
    # FAILURE-FIRST (red): a critical safety/PII criterion misses while everything else is
    # excellent. A naive weighted average would pass; the gate must REJECT on the critical.
    crit = [
        {"name": "aesthetics", "score": 0.98},
        {"name": "prompt_fidelity", "score": 0.95},
        {"name": "no_pii_or_unsafe", "score": 0.10, "critical": True},
    ]
    v = grade(crit, tau=0.70)
    assert v["decision"] == REJECT
    assert v["reason"] == "critical_failure"
    assert "no_pii_or_unsafe" in v["critical_failures"]


def test_critical_failure_fixed_then_accepts():
    # GREEN: once the critical criterion is fixed, the same artifact accepts.
    crit = [
        {"name": "aesthetics", "score": 0.98},
        {"name": "prompt_fidelity", "score": 0.95},
        {"name": "no_pii_or_unsafe", "score": 0.97, "critical": True},
    ]
    v = grade(crit, tau=0.70)
    assert v["decision"] == ACCEPT
    assert v["critical_failures"] == []


def test_weighting_shifts_the_score():
    # Up-weighting the weak criterion drags the point score down vs. up-weighting a strong one.
    crit_weak = [{"name": "strong", "score": 0.95, "weight": 1.0},
                 {"name": "weak", "score": 0.30, "weight": 5.0}]
    crit_strong = [{"name": "strong", "score": 0.95, "weight": 5.0},
                   {"name": "weak", "score": 0.30, "weight": 1.0}]
    assert grade(crit_weak)["point_score"] < grade(crit_strong)["point_score"]


def test_no_criteria_is_review():
    v = grade([])
    assert v["decision"] == REVIEW
    assert v["reason"] == "no_evidence"


def test_zero_total_weight_is_review():
    v = grade([{"name": "x", "score": 0.9, "weight": 0.0}])
    assert v["decision"] == REVIEW
    assert v["reason"] == "no_evidence"


def test_score_out_of_range_raises():
    with pytest.raises(ValueError):
        grade([{"name": "x", "score": 1.4}])
    with pytest.raises(ValueError):
        grade([{"name": "x", "score": -0.1}])
    with pytest.raises(ValueError):
        grade([{"name": "x", "score": 0.5, "weight": -1.0}])


def test_more_evidence_narrows_the_interval():
    # Same mean score, more concurring criteria -> tighter credible interval.
    few = grade([{"name": f"c{i}", "score": 0.9} for i in range(2)])
    many = grade([{"name": f"c{i}", "score": 0.9} for i in range(8)])
    width_few = few["ci"][1] - few["ci"][0]
    width_many = many["ci"][1] - many["ci"][0]
    assert width_many < width_few


def test_verdict_is_serializable_and_complete():
    v = grade([{"name": "c", "score": 0.8}])
    for key in ("decision", "reason", "score", "point_score", "ci", "cred", "tau",
                "n_criteria", "critical_failures", "alpha", "beta"):
        assert key in v
    assert v["decision"] in (ACCEPT, REVIEW, REJECT)
    assert 0.0 <= v["score"] <= 1.0
    assert len(v["ci"]) == 2 and v["ci"][0] <= v["ci"][1]


# --- dependency-free Beta math ---------------------------------------------------------

def test_betai_is_regularized_and_bounded():
    assert G._betai(2.0, 3.0, 0.0) == 0.0
    assert G._betai(2.0, 3.0, 1.0) == 1.0
    # I_0.5(a, a) = 0.5 by symmetry of a symmetric Beta.
    assert abs(G._betai(3.0, 3.0, 0.5) - 0.5) < 1e-9
    assert abs(G._betai(7.5, 7.5, 0.5) - 0.5) < 1e-9


def test_betai_matches_known_uniform_cdf():
    # Beta(1,1) is Uniform(0,1): I_x(1,1) == x.
    for x in (0.1, 0.37, 0.5, 0.83):
        assert abs(G._betai(1.0, 1.0, x) - x) < 1e-9


def test_beta_ppf_inverts_betai():
    for (a, b, p) in [(1.0, 1.0, 0.5), (2.0, 5.0, 0.25), (10.0, 3.0, 0.9)]:
        x = G._beta_ppf(p, a, b)
        assert abs(G._betai(a, b, x) - p) < 1e-6


def test_ppf_uniform_median_is_half():
    assert abs(G._beta_ppf(0.5, 1.0, 1.0) - 0.5) < 1e-6


def test_public_surface_exports_graded():
    assert hasattr(pl, "grade")
    assert pl.ACCEPT == "ACCEPT" and pl.REVIEW == "REVIEW" and pl.REJECT == "REJECT"
