"""Which picks actually paid? Ask the ledger, not the theory.

The ranker bids on two different things and the difference decides the mission:

  efficiency  -- replay a cleared level faster. Bounded: 18.68pp exists in
                 total, so efficiency-only tops out near 49% corpus.
  new level   -- clear something never cleared. Where the other ~65pp lives.

Reasoning says the second must dominate. Reasoning is not evidence, and the
loop has 28 waves of history sitting on disk. This asks what the record says:
per wave, how much corpus arrived, split by whether the games drafted still had
levels they had never cleared.

Read-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc import auto_corpus as ac  # noqa: E402
from evals.arc.rhae import load_baselines  # noqa: E402

LEDGER = Path("eval/arc-results/auto-corpus-ledger.jsonl")


def main() -> int:
    baselines = load_baselines()
    runs = ac.all_runs(baselines)

    # Levels never cleared, per game, as of NOW. A game at its ceiling had no
    # new-level upside on any wave that drafted it.
    unclear = {}
    for game, rs in runs.items():
        lv = max(r["levels_completed"] for r in rs)
        unclear[game] = len(baselines[game]) - lv

    waves = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            waves.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    print(f"{'wave':<6}{'games':<26}{'unclear':>9}{'delta_pp':>10}")
    print("-" * 52)

    buckets: dict[str, list[float]] = {"has_unclear": [], "all_capped": []}
    for w in waves:
        games = w.get("games") or []
        if not games:
            continue
        delta = (w.get("corpus_after", 0) - w.get("corpus_before", 0)) * 100
        room = sum(unclear.get(g, 0) for g in games)
        key = "has_unclear" if room > 0 else "all_capped"
        buckets[key].append(delta)
        print(f"{w.get('wave', '?'):<6}{','.join(games):<26}{room:>9}{delta:>10.3f}")

    print("-" * 52)
    for key, label in (("has_unclear", "waves drafting unclear levels"),
                       ("all_capped", "waves drafting only capped games")):
        vals = buckets[key]
        if not vals:
            print(f"{label:<34} no waves")
            continue
        total = sum(vals)
        paid = sum(1 for v in vals if v > 0.001)
        print(f"{label:<34} n={len(vals):<4} total={total:>7.3f}pp  "
              f"mean={total/len(vals):>6.3f}pp  paid={paid}/{len(vals)}")

    # Per-game: what did drafting this game actually return, and does it still
    # have anywhere new to go?
    print("\nper game: total corpus delta across every wave that drafted it")
    per: dict[str, list[float]] = {}
    for w in waves:
        delta = (w.get("corpus_after", 0) - w.get("corpus_before", 0)) * 100
        for g in (w.get("games") or []):
            per.setdefault(g, []).append(delta)
    rows = sorted(per.items(), key=lambda kv: -sum(kv[1]))
    print(f"{'game':<7}{'picks':>7}{'total_pp':>10}{'unclear_left':>14}")
    for g, vals in rows:
        print(f"{g:<7}{len(vals):>7}{sum(vals):>10.3f}{unclear.get(g, 0):>14}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
