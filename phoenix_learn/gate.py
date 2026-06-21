"""The measured-gain adoption gate (ported from goose/tools/sia_h_run.py:decide).

A candidate is ADOPT_ELIGIBLE only when, on the held-out PRIVATE split, it clears every bar:
  * enough evidence:        private_n >= ADOPT_MIN_N
  * a real margin:          (sel_acc - gen0_acc) >= ADOPT_MARGIN  AND
                            (sel_correct - gen0_correct) >= ADOPT_MIN_NET
  * does no harm:           zero right->wrong regressions
  * strictly better:        sel_acc > gen0_acc
Anti-gaming hits short-circuit to REJECT_GAMING_DETECTED; thin evidence -> EXPERIMENTAL_SMOKE_TEST;
anything else -> REJECT. These thresholds match the live Goose loop's standard.
"""
from __future__ import annotations

ADOPT_MIN_N = 20      # held-out PRIVATE rows required before any auto-adoption
ADOPT_MARGIN = 0.10   # +10pp accuracy on PRIVATE
ADOPT_MIN_NET = 2     # +2 net newly-correct rows on PRIVATE


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
