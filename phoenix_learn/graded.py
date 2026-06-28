"""phoenix_learn.graded — a graded/Bayesian acceptance gate for generative output (issue #18).

WHY THIS EXISTS
---------------
The core `phoenix_sense` gate is binary: GREEN/RED on an objective signal (exit code, file
hash, regex). That is exactly right for *deterministic* code — a test either passes or it
does not. It is the wrong shape for *non-deterministic generative output* (audio, video,
image, prose): such an artifact is almost never wholly right or wholly wrong, so a single
hard threshold either rubber-stamps mediocre work or rejects good-enough work on noise.

`graded` adds a second, *scored* acceptance mode alongside (never replacing) the binary
gate. An upstream grader (a human, a model-judge, or a metric — this module does NOT invent
the scores, mirroring how `gate.decide` never runs the tasks) scores the artifact against a
weighted rubric. We fold those per-criterion scores into a conjugate **Beta posterior** over
the artifact's latent quality and return one of three honest verdicts:

  * ACCEPT  — we are `cred`-confident quality is at least `tau` (credible lower bound >= tau).
  * REJECT  — we are `cred`-confident quality is below `tau` (credible upper bound < tau).
  * REVIEW  — genuinely borderline: the credible interval straddles `tau`. Binary gating
              cannot express this; here it is a first-class outcome that says "get more
              evidence / escalate to a human" instead of guessing.

THE HONESTY CORE
----------------
A criterion may be marked `critical` (e.g. a safety / no-PII / no-unsafe-content check). If
any critical criterion scores below `critical_floor`, the verdict is REJECT regardless of how
high everything else scored — a critical miss can never be averaged away by aesthetics. This
mirrors the anti-gaming short-circuit in `gate.decide` and is the property the failure-first
acceptance test pins.

The module is deterministic, offline, and dependency-free (stdlib `math` only); the Beta CDF
(`_betai`, regularized incomplete beta via a Lentz continued fraction) and its inverse
(`_beta_ppf`, by bisection) carry the credible interval with no numpy/scipy.

It decides; it does not act. Pair the verdict with `phoenix_accept` so a generative artifact
is accepted only behind a recorded trace — the binary gate stays the gate for code, this is
the gate for media.
"""
from __future__ import annotations

import math
from typing import Iterable

ACCEPT = "ACCEPT"
REVIEW = "REVIEW"
REJECT = "REJECT"

# Defaults. `UNIT_EVIDENCE` is how many pseudo-observations one unit of rubric weight is
# worth; total evidence scales with the summed weight, so more concurring criteria tighten
# the posterior. `TAU`/`CRED` are the acceptance threshold and the credible level.
UNIT_EVIDENCE = 4.0
TAU = 0.70
CRED = 0.80
CRITICAL_FLOOR = 0.5


def _betacf(a: float, b: float, x: float, itmax: int = 300, eps: float = 1e-12) -> float:
    """Continued fraction for the incomplete beta function (Lentz's algorithm)."""
    tiny = 1e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) = P(Beta(a, b) <= x). Deterministic, no deps."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(ln_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(p: float, a: float, b: float, eps: float = 1e-9, itmax: int = 200) -> float:
    """Inverse Beta CDF (quantile) by bisection on the monotone _betai."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(itmax):
        mid = 0.5 * (lo + hi)
        if _betai(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < eps:
            break
    return 0.5 * (lo + hi)


def _coerce(criteria: Iterable[dict]):
    """Validate and normalize criteria. Returns (rows, critical_failures, total_weight)."""
    rows = []
    critical_failures = []
    total_weight = 0.0
    for i, c in enumerate(criteria):
        name = c.get("name", f"criterion_{i}")
        score = float(c.get("score"))
        weight = float(c.get("weight", 1.0))
        critical = bool(c.get("critical", False))
        if not (0.0 <= score <= 1.0):
            raise ValueError(f"criterion {name!r} score {score} out of range [0,1]")
        if weight < 0.0:
            raise ValueError(f"criterion {name!r} weight {weight} is negative")
        rows.append((name, score, weight, critical))
        total_weight += weight
    return rows, critical_failures, total_weight


def grade(
    criteria: Iterable[dict],
    *,
    tau: float = TAU,
    cred: float = CRED,
    unit_evidence: float = UNIT_EVIDENCE,
    prior: tuple = (1.0, 1.0),
    critical_floor: float = CRITICAL_FLOOR,
) -> dict:
    """Grade a generative artifact against a weighted rubric and return an honest verdict.

    Each entry of `criteria` is a dict: {"name": str, "score": float in [0,1],
    "weight": float >= 0 (default 1.0), "critical": bool (default False)}.

    Returns a JSON-serializable verdict dict with keys: decision, reason, score (posterior
    mean), point_score (weighted mean, or None when no evidence), ci [lo, hi] credible
    interval, cred, tau, n_criteria, critical_failures, alpha, beta.
    """
    rows, _cf, total_weight = _coerce(criteria)
    prior_a, prior_b = float(prior[0]), float(prior[1])

    critical_failures = [name for (name, score, _w, crit) in rows
                         if crit and score < critical_floor]

    # Posterior parameters: evidence scales with summed weight, so concurring criteria sharpen.
    succ = sum(unit_evidence * w * s for (_n, s, w, _c) in rows)
    fail = sum(unit_evidence * w * (1.0 - s) for (_n, s, w, _c) in rows)
    alpha = prior_a + succ
    beta = prior_b + fail

    mean = alpha / (alpha + beta)
    tail = (1.0 - cred) / 2.0
    lo = _beta_ppf(tail, alpha, beta)
    hi = _beta_ppf(1.0 - tail, alpha, beta)
    point = (sum(w * s for (_n, s, w, _c) in rows) / total_weight) if total_weight > 0 else None

    verdict = {
        "score": round(mean, 4),
        "point_score": (round(point, 4) if point is not None else None),
        "ci": [round(lo, 4), round(hi, 4)],
        "cred": cred,
        "tau": tau,
        "n_criteria": len(rows),
        "critical_failures": critical_failures,
        "alpha": round(alpha, 6),
        "beta": round(beta, 6),
    }

    if critical_failures:
        verdict.update(decision=REJECT, reason="critical_failure")
    elif total_weight <= 0.0:
        verdict.update(decision=REVIEW, reason="no_evidence")
    elif lo >= tau:
        verdict.update(decision=ACCEPT, reason="confident_above_tau")
    elif hi < tau:
        verdict.update(decision=REJECT, reason="confident_below_tau")
    else:
        verdict.update(decision=REVIEW, reason="borderline")
    return verdict


def is_accept(verdict: dict) -> bool:
    """True only on a clean ACCEPT verdict."""
    return verdict.get("decision") == ACCEPT


def summary(verdict: dict) -> str:
    """One-line, PII-free summary for logs and the phoenix trace."""
    lo, hi = verdict["ci"]
    return (f"{verdict['decision']} ({verdict['reason']}) "
            f"score={verdict['score']} ci=[{lo},{hi}] "
            f"tau={verdict['tau']} cred={verdict['cred']} n={verdict['n_criteria']}")
