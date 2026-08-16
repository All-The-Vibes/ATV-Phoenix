"""At what cost does a level ACTUALLY fall? Measure before choosing a cutoff.

RHAE scores a level `min(1.15, (human / ai) ** 2)`. The decay is quadratic, so
a level cleared at 10x the human action count is worth 0.01 of the 1.15 on
offer -- under one percent. That makes "how long should a stuck run keep
trying" an empirical question rather than a taste one, and the corpus has
hundreds of cleared levels on disk to answer it.

The number this is chosen to inform is a stall cutoff: actions since the last
clear, as a multiple of the human baseline for the level being attempted. Set
it too low and slow-but-progressing runs die -- wave r2 cut sk48 at turn 26 of
80 while it held a complete and correct strategy, and that mistake is on the
record. Set it too high and 29,846 actions go where 100% of them buy nothing.

So: the distribution of ratios at which levels have historically been cleared.
A cutoff above the top of that distribution cannot kill a clear that would have
happened, because no clear has ever happened there.

Read-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.rhae import load_baselines  # noqa: E402

RESULTS = Path("eval/arc-results")


def main() -> int:
    baselines = load_baselines()
    ratios: list[tuple[float, str, int]] = []
    skipped = 0

    for path in sorted(RESULTS.glob("*.json")):
        name = path.name
        if any(k in name for k in ("queue", "status", "health", "skills",
                                   "mechanics", "ledger", "baseline")):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        # A result file wraps its games in `runs`; the per-level attribution
        # lives there, not at the top level, where only a rolled-up total is.
        for run in payload.get("runs") or []:
            if not isinstance(run, dict):
                continue
            game = run.get("game")
            human = baselines.get(game)
            per_level = run.get("level_actions")
            if not game or not human or not per_level:
                skipped += 1
                continue
            done = run.get("levels_completed", 0)
            for index, spent in enumerate(per_level[:done], start=1):
                if index > len(human) or not spent:
                    continue
                base = human[index - 1] or 1
                ratios.append((spent / base, game, index))

    if not ratios:
        print("no per-level data found")
        return 1

    ratios.sort()
    values = [r for r, _, _ in ratios]
    n = len(values)

    def pct(p: float) -> float:
        return values[min(n - 1, int(n * p))]

    print(f"cleared levels with per-level attribution: {n}"
          f"   (runs without it: {skipped})")
    print(f"\nratio of AI actions to human baseline, at the moment a level FELL")
    for p in (0.50, 0.75, 0.90, 0.95, 0.99, 1.00):
        r = pct(p if p < 1 else 0.999999)
        # What that clear was worth, to make the tail's value concrete.
        worth = min(1.15, (1 / r) ** 2) if r else 1.15
        print(f"  p{int(p*100):<3} {r:>8.2f}x   a clear there scores {worth:.4f}")

    print(f"\n  max observed {values[-1]:.2f}x")
    print("\nslowest clears on record:")
    for r, game, lv in ratios[-8:][::-1]:
        worth = min(1.15, (1 / r) ** 2)
        print(f"  {game} level {lv:<2} {r:>7.2f}x  worth {worth:.4f}")

    print("\nhow many clears a cutoff would have destroyed:")
    for cut in (3, 4, 5, 6, 8, 10, 15, 20):
        lost = sum(1 for r in values if r > cut)
        lost_worth = sum(min(1.15, (1 / r) ** 2) for r in values if r > cut)
        print(f"  cut at {cut:>2}x human: {lost:>4} of {n} clears lost"
              f"  ({lost/n:>5.1%}), total RHAE forgone {lost_worth:>6.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
