"""Does a run stop once the level it is on can no longer pay?

RHAE scores a level `min(1.15, (human / ai) ** 2)`. Quadratic, so the value of
a clear collapses with the action count: 2x human is worth 0.25, 10x is worth
0.01, 20x is worth 0.0025. Past a point the level being attempted cannot repay
the actions being spent on it, and every further action is pure wall clock.

That point is passed constantly. Measured 2026-08-16 across the corpus: 35
stalls, 29,846 actions, with 95-100% of a stalled run's budget spent AFTER its
last clear -- `vc33-ev35` at 1056 of 1059 actions (100%), `re86-ev34` at 862 of
882 (98%). The existing guards do not catch it. `patience` counts TURNS without
progress and treats learning a mechanic as progress, and its own source note
concedes a determined agent can keep registering slightly different strings to
buy turns; `action_cap` and `max_turns` are ceilings on the whole run, blind to
whether the current level is still winnable.

The cutoff is chosen from history rather than taste. Of 905 levels actually
cleared, the ratio of AI actions to human baseline at the moment of the clear:

    p50 1.46x   p75 3.33x   p90 7.05x   p95 10.05x   p99 24.52x

Cutting at 10x would have destroyed 46 of those 905 clears -- 5.1% -- worth
0.218 RHAE in total, because every one of them was already scoring under 0.01.
Cutting at 5x costs 2.599 RHAE, twelve times more, which is why 5x was not
chosen despite recovering more wall clock.

The number this pins is the SHAPE: a run whose current level has become
worthless must stop. STALL_CUT can move without invalidating that.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.codeact_agent import STALL_CUT, level_exhausted  # noqa: E402


def main() -> int:
    failures: list[str] = []
    print(f"STALL_CUT = {STALL_CUT}x human baseline")

    # 1. The observed disasters must be caught. Both of these ran to the end of
    #    their budget without clearing the level they were on.
    print("\nruns that actually happened:")
    cases = [
        ("sk48-ev34", 1010, 61, True),   # 16.6x human
        ("tn36-ev29", 617, 32, True),    # 19.3x human
        ("bp35 level 1", 1648, 651, False),   # 2.5x -- slow, still plausible
        ("a clean clear", 30, 60, False),     # under human, obviously keep
        ("2x human", 120, 60, False),         # worth 0.25, keep
    ]
    for name, spent, par, should_cut in cases:
        cut = level_exhausted(spent, par)
        ratio = spent / par
        worth = min(1.15, (par / spent) ** 2)
        verdict = "CUT" if cut else "keep"
        print(f"  {name:<16} {spent:>5} vs {par:<5} = {ratio:>6.1f}x  "
              f"worth {worth:.4f}  -> {verdict}")
        if cut != should_cut:
            failures.append(
                f"{name}: {ratio:.1f}x human, worth {worth:.4f} -- expected "
                f"{'CUT' if should_cut else 'keep'}, got {verdict}"
            )

    # 2. A missing baseline must never cut. Eight of the 25 games publish no
    #    per-level baseline, and killing a run because the API was quiet would
    #    be the harness inventing a failure.
    if level_exhausted(99999, None) or level_exhausted(99999, 0):
        failures.append("a run was cut with no baseline to judge it against")
    print(f"\n  no baseline available -> "
          f"{'CUT (wrong)' if level_exhausted(99999, None) else 'keep (right)'}")

    # 3. The boundary is where the docstring says it is.
    par = 100
    if level_exhausted(par * STALL_CUT - 1, par):
        failures.append("cut fired below the threshold")
    if not level_exhausted(par * STALL_CUT + 1, par):
        failures.append("cut did not fire above the threshold")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK    a level that can no longer pay ends the run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
