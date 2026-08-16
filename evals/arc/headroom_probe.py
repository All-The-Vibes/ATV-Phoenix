"""How much of the ranker's expected value is aimed at levels never cleared?

The structural constraint on this mission: efficiency work on already-cleared
levels is bounded. A game with `levels` of `total` cleared can never exceed
sum(1..levels)/sum(1..total) * 1.15 no matter how fast it plays. Everything
above that line has to come from clearing a level that has never fallen.

So the question that decides where compute should go is not "which game ranks
highest", it is "what is the ranker BUYING when it picks". This dumps the
decomposition the ranker already computes internally but never prints:

  efficiency_room  -- play cleared levels faster (bounded, and often zero)
  next_level_room  -- clear the next level (where the remaining corpus lives)

Read-only. Measures, changes nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc import auto_corpus as ac  # noqa: E402
from evals.arc.rhae import load_baselines  # noqa: E402


def main() -> int:
    baselines = load_baselines()
    runs = ac.all_runs(baselines)
    barren = ac.barren_streaks()
    attempts = ac.picks_so_far()
    n_games = len(baselines) or 1
    share = 1.0 / n_games

    rows = []
    tot_eff = tot_next = tot_raw_next = 0.0
    cleared = unclear = 0

    for game, rs in runs.items():
        best = max(r["_score"] for r in rs)
        levels = max(r["levels_completed"] for r in rs)
        n_levels = len(baselines[game])
        weight_sum = sum(range(1, n_levels + 1)) or 1
        ceiling_now = sum(range(1, levels + 1)) / weight_sum * 1.15
        eff = max(0.0, ceiling_now - best)
        raw_next = (((levels + 1) / weight_sum * 1.15)
                    if levels < n_levels else 0.0)
        nxt = raw_next / (1.0 + barren.get(game, 0))

        cleared += levels
        unclear += n_levels - levels
        tot_eff += eff * share
        tot_next += nxt * share
        tot_raw_next += raw_next * share

        rows.append((eff * share, nxt * share, raw_next * share, game, levels,
                     n_levels, best, barren.get(game, 0), attempts.get(game, 0)))

    rows.sort(key=lambda r: -(r[0] + r[1]))

    print(f"{'game':<7}{'lv':>7}{'best':>8}{'eff_pp':>9}{'next_pp':>9}"
          f"{'next_raw':>10}{'barren':>8}{'tried':>7}")
    print("-" * 66)
    for eff, nxt, raw, game, lv, n, best, b, t in rows:
        print(f"{game:<7}{f'{lv}/{n}':>7}{best:>7.1%}{eff*100:>9.2f}"
              f"{nxt*100:>9.2f}{raw*100:>10.2f}{b:>8}{t:>7}")

    total = tot_eff + tot_next
    print("-" * 66)
    print(f"levels cleared {cleared}, never cleared {unclear}")
    print(f"\nheadroom the ranker is bidding on:")
    print(f"  efficiency (replay cleared levels) : {tot_eff*100:>7.2f}pp"
          f"  {tot_eff/total:>6.1%}")
    print(f"  next level (clear something new)   : {tot_next*100:>7.2f}pp"
          f"  {tot_next/total:>6.1%}")
    print(f"  next level BEFORE barren decay     : {tot_raw_next*100:>7.2f}pp")

    corpus, _ = ac.corpus_now(baselines)
    print(f"\ncorpus now {corpus:.2%}, target 95.50%, gap "
          f"{(0.955 - corpus)*100:.2f}pp")
    print(f"total headroom the ranker can even SEE: {total*100:.2f}pp")
    if total < (0.955 - corpus):
        print("  -> the ranker cannot see enough headroom to reach the target;")
        print("     the gap is in levels it is not bidding on at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
