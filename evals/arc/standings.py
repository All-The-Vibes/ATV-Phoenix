"""Corpus standings: the best scorable run per game, scored the official way.

Free: reads what is already on disk, no API calls beyond the baseline fetch.

Written because the standings kept being quoted from memory and kept being
wrong. Three traps live in this data and each one produced a confident wrong
number at some point:

`score_run` keys on ``run["game"]``. Passing ``game_id`` raises KeyError, and a
try/except around the call turns that into a score of zero -- which reads as
"we scored nothing" rather than "the scorer was never asked". Every game came
back 0.00% that way, twice.

The results directory holds artifacts from more than one agent. `novelty.json`
is the superseded vision_agent's all-25 sweep at 2,000 actions a game; any
rollup that ignores it under-counts coverage, and any rollup that treats it as
a real attempt over-counts effort. It is included here because a 0/9 record IS
the current best for a game never otherwise played, and excluded from nothing.

A game is worth its BEST run, because `EnvironmentScoreList.score` returns
max(...) despite a docstring promising an average. So the best run is chosen by
SCORE, not by level count, and those disagree: sb26's 7/8 in 325 actions scores
73.74% while its 8/8 in 245 scores 71.48%, because level 8 cost 56 actions
against a human 18 and efficiency is squared. Completing more is not the same
as scoring more, and the scoreboard is the arbiter.

Runs that did not start at level 1, or that self-declare `scorable: false`, are
excluded: those are probes, and counting them would be scoring ourselves on
questions we set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.rhae import load_baselines, score_run  # noqa: E402

RESULTS = Path(__file__).resolve().parents[2] / "eval" / "arc-results"
PRIME_AGENT = 0.955


def best_per_game(baselines: dict[str, list[int]]) -> dict[str, tuple]:
    best: dict[str, tuple] = {}
    for path in sorted(RESULTS.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for run in payload.get("runs") or []:
            if not isinstance(run, dict) or "levels_completed" not in run:
                continue
            game = str(run.get("game") or "").split("-")[0]
            if game not in baselines:
                continue
            if run.get("start_level", 1) != 1 or run.get("scorable") is False:
                continue
            try:
                score = score_run([run], baselines)["rhae_total"]
            except (KeyError, TypeError, ZeroDivisionError):
                continue
            if game not in best or score > best[game][0]:
                best[game] = (score, run, path.name)
    return best


def main() -> int:
    baselines = load_baselines()
    best = best_per_game(baselines)

    print(f"{'game':<7}{'lv':>4}{'/of':>5}{'acts':>7}{'human':>7}{'score':>9}   source")
    print("-" * 62)
    total = 0.0
    for game in sorted(best, key=lambda g: -best[g][0]):
        score, run, source = best[game]
        total += score
        print(
            f"{game:<7}{run['levels_completed']:>4}{len(baselines[game]):>5}"
            f"{run.get('actions_spent', 0):>7}{sum(baselines[game]):>7}"
            f"{score:>9.2%}   {source}"
        )
    for game in sorted(g for g in baselines if g not in best):
        print(
            f"{game:<7}{'-':>4}{len(baselines[game]):>5}{'-':>7}"
            f"{sum(baselines[game]):>7}{0.0:>9.2%}   never scored"
        )

    levels = sum(r["levels_completed"] for _, r, _ in best.values())
    available = sum(len(v) for v in baselines.values())
    corpus = total / len(baselines)

    print("-" * 62)
    print(f"games with a scorable record : {len(best)} of {len(baselines)}")
    print(f"games with a level cleared   : "
          f"{sum(1 for _, r, _ in best.values() if r['levels_completed'])} of {len(baselines)}")
    print(f"levels cleared               : {levels} of {available}")
    print(f"CORPUS RHAE                  : {corpus:.2%}")
    print(f"Prime Agent                  : {PRIME_AGENT:.2%}")
    print(f"gap                          : {PRIME_AGENT - corpus:.2%}")
    # One perfect game is worth 4% of the corpus, so the gap is not closed by
    # perfecting the three that work. It is closed by the twenty-two at zero.
    print(f"\na perfect game is worth {1 / len(baselines):.2%} of the corpus; "
          f"{sum(1 for _, r, _ in best.values() if not r['levels_completed'])} games "
          f"have never cleared a level")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
