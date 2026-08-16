"""Does the selector value levels it has never cleared, or only the next one?

THE MISSION CANNOT BE WON ON EFFICIENCY. Measured 2026-08-16: replaying every
cleared level at the RHAE cap is worth 18.68pp, against a corpus of 30.83% and
a target of 95.50%. Perfect efficiency lands near 49% and stops. The other
~46pp is behind the 83 levels that have never been cleared.

The ranker scored exactly ONE of those levels per game -- the immediate next
one -- and assigned zero to everything past it. 25 games, so 25 of 83 unclear
levels carried value and 58 carried none. A game at 1 of 9 was bid as though
clearing level 2 were the whole prize, while the seven levels behind it, worth
far more under RHAE's index weighting, were invisible.

That is not a tuning choice, it is a horizon of one. This check pins the
horizon open. It is deliberately about SHAPE, not about a specific number:
whatever decay is chosen, a level that exists must not be worth zero, and a
game with more unclear levels ahead must not be worth less than one with fewer.

Offline and deterministic -- no scorecards, no network. The fixture is the real
corpus shape as of 2026-08-16 so the totals mean something.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.auto_corpus import ladder_room  # noqa: E402

# game -> (levels proven, levels total, best score, barren streak).
CORPUS = {
    "ka59": (5, 7, 0.0914, 3), "cd82": (6, 6, 0.6168, 9),
    "r11l": (6, 6, 0.6581, 2), "dc22": (4, 6, 0.2745, 1),
    "ar25": (5, 8, 0.2675, 0), "sc25": (4, 6, 0.3170, 1),
    "vc33": (5, 7, 0.3807, 1), "re86": (4, 8, 0.1501, 0),
    "lp85": (8, 8, 0.8390, 0), "tu93": (5, 9, 0.1578, 1),
    "sb26": (8, 8, 0.8600, 0), "cn04": (4, 6, 0.3515, 2),
    "tr87": (6, 6, 0.8650, 1), "sp80": (2, 6, 0.0999, 0),
    "ls20": (3, 7, 0.0559, 7), "su15": (3, 9, 0.0773, 0),
    "s5i5": (3, 8, 0.0982, 2), "m0r0": (2, 6, 0.1143, 1),
    "tn36": (1, 7, 0.0006, 0), "g50t": (2, 7, 0.0411, 3),
    "wa30": (3, 9, 0.1186, 1), "lf52": (3, 10, 0.0893, 1),
    "bp35": (1, 9, 0.0000, 0), "sk48": (1, 8, 0.0319, 0),
    "ft09": (6, 6, 1.1500, 0),
}
SHARE = 1.0 / len(CORPUS)


def one_level_only(proven: int, n_levels: int, barren: int) -> float:
    """The old horizon: the immediate next level, nothing behind it."""
    if proven >= n_levels:
        return 0.0
    weight_sum = sum(range(1, n_levels + 1)) or 1
    return (proven + 1) / weight_sum * 1.15 / (1.0 + barren)


def efficiency_room(proven: int, n_levels: int, best: float) -> float:
    weight_sum = sum(range(1, n_levels + 1)) or 1
    ceiling = sum(range(1, proven + 1)) / weight_sum * 1.15
    return max(0.0, ceiling - best)


def main() -> int:
    failures: list[str] = []

    # 1. A level that exists is not worth zero. bp35 has EIGHT unclear levels;
    #    valuing it the same as a game with one is the defect itself.
    deep = ladder_room(1, 9, 0)
    shallow = one_level_only(1, 9, 0)
    print(f"bp35-shape (1 of 9 cleared, 8 unclear)")
    print(f"  one-level horizon : {shallow:.4f}")
    print(f"  ladder horizon    : {deep:.4f}")
    if deep <= shallow:
        failures.append(
            f"levels past the next are worth nothing: ladder {deep:.4f} "
            f"is not above the single-level value {shallow:.4f}"
        )

    # 2. Every remaining level counts, at every shape -- not just the one at the
    #    front. The first draft of this check compared a 1-of-3 game against a
    #    1-of-9 one and demanded the longer ladder score higher. That was wrong:
    #    RHAE normalises by the game's own weight sum, so a 3-level game has
    #    fewer, individually richer levels, and 1-of-3 outranking 1-of-9 is the
    #    scoring working correctly rather than a defect. The claim that actually
    #    holds is per-shape: whatever the game, a ladder with more than one
    #    level left must be worth more than its first rung alone.
    print("\nevery remaining level counts, across shapes")
    shapes = [(1, 9), (1, 8), (2, 6), (3, 10), (4, 8), (5, 9), (1, 3)]
    for proven, n in shapes:
        lad = ladder_room(proven, n, 0)
        one = one_level_only(proven, n, 0)
        unclear_here = n - proven
        flag = "" if (unclear_here < 2 or lad > one) else "   <-- FLAT"
        print(f"  {proven} of {n} ({unclear_here} unclear): "
              f"one={one:.4f} ladder={lad:.4f}{flag}")
        if unclear_here >= 2 and lad <= one:
            failures.append(
                f"{proven} of {n}: {unclear_here} levels unclear but the ladder "
                f"({lad:.4f}) counts no more than the first rung ({one:.4f})"
            )

    # 3. A fully-cleared game still has no new-level value. The barren decay and
    #    the mined-out benching both depend on this staying true.
    if ladder_room(6, 6, 0) != 0.0:
        failures.append("a fully cleared game was given new-level value")

    # 4. Whole-corpus shape: what the ranker can SEE, against what the mission
    #    needs. Efficiency is bounded; if the unclear-level term is a rounding
    #    error next to it, the ranker is bidding on a game it cannot win.
    eff = sum(efficiency_room(p, n, best) * SHARE
              for p, n, best, _ in CORPUS.values())
    lad = sum(ladder_room(p, n, br) * SHARE for p, n, _, br in CORPUS.values())
    old = sum(one_level_only(p, n, br) * SHARE
              for p, n, _, br in CORPUS.values())
    unclear = sum(n - p for p, n, _, _ in CORPUS.values())
    print(f"\nwhole corpus ({unclear} levels never cleared)")
    print(f"  efficiency headroom      : {eff*100:>6.2f}pp")
    print(f"  unclear-level, one-level : {old*100:>6.2f}pp")
    print(f"  unclear-level, ladder    : {lad*100:>6.2f}pp")

    # Half of efficiency is a low bar on purpose. The claim being defended is
    # "the unclear levels are a material part of the bid", not a preference for
    # any particular decay -- a check that pinned the ratio would fail the next
    # time the corpus moves, and would be measuring the corpus, not the code.
    if lad < eff * 0.5:
        failures.append(
            f"unclear levels are still marginal: {lad*100:.2f}pp against "
            f"{eff*100:.2f}pp of efficiency, on {unclear} uncleared levels"
        )

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK    the horizon covers every level, not just the next one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
