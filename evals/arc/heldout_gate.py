"""Gate a policy proposal on ARC games it never saw (issue #177, step 3).

The gap this closes was found while reviewing `prime-agent` and never filed: the
acceptance gate measures the work product, not the harness. A change to how the
agent behaves can look clean on the work in front of it and still be worse. Held-out
environments are the check that catches that, and `phoenix_learn.gate.decide` is
already the right judge.

The split is by GAME, never by run. Splitting on (game, seed) would place the same
environment on both sides, and a proposer tuned against a game in the private split
is memorizing rather than generalizing. Seeds multiply n inside a split, they never
cross one. This is the same property `phoenix_learn.split.forbidden_strings`
enforces for text fixtures.

PRIVATE is scored exactly once, for the baseline and the selected candidate only.

Usage::

    python -m evals.arc.heldout_gate --budget 1200 --seeds 5 --out eval/arc-results/gate.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.arc.policies import Policy  # noqa: E402
from phoenix_learn.gate import decide  # noqa: E402
from phoenix_learn.gate import transitions  # noqa: E402
from phoenix_learn.split import split_fixture  # noqa: E402

TERMINAL = ("GameState.WIN", "GameState.GAME_OVER")

# The candidate space a proposer may move. gen_0 is the shipped configuration.
CANDIDATES = {
    "gen0_count_grid8": {"strategy": "count", "grid_step": 8},
    "cand_count_grid4": {"strategy": "count", "grid_step": 4},
    "cand_change_grid8": {"strategy": "change", "grid_step": 8},
}
BASELINE = "gen0_count_grid8"


def play(arc, game: str, config: dict, budget: int, seed: int) -> int:
    """Levels completed by one config on one game under one seed."""
    env = arc.make(game, include_frame_data=True)
    frame = env.reset()
    policy = Policy("novelty", env.action_space, seed=seed, config=config)
    best = 0
    for _ in range(budget):
        action, data = policy.act(frame)
        try:
            nxt = env.step(action, data) if data else env.step(action)
        except Exception:
            continue
        if nxt is None:
            continue
        frame = nxt
        policy.observe(frame)
        best = max(best, frame.levels_completed)
        if str(frame.state) in TERMINAL:
            frame = env.reset()
    return best


def score(arc, games: list[str], config: dict, budget: int, seeds: int) -> dict:
    """One row per (game, seed). A row is correct when the config cleared a level."""
    rows = []
    for game in games:
        for seed in range(seeds):
            levels = play(arc, game, config, budget, seed)
            rows.append({"intent": f"{game}#{seed}", "ok": levels > 0, "levels": levels})
    correct = sum(1 for r in rows if r["ok"])
    return {
        "rows": rows,
        "correct": correct,
        "n": len(rows),
        "acc": correct / len(rows) if rows else 0.0,
        "levels": sum(r["levels"] for r in rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--salt", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import arc_agi

    arc = arc_agi.Arcade()
    games = sorted(e.game_id.split("-")[0] for e in arc.get_environments())

    # Split by game id, so no environment appears on two sides of the wall.
    pub, dev, priv = split_fixture([{"intent": g} for g in games], args.salt)
    pub = [r["intent"] for r in pub]
    dev = [r["intent"] for r in dev]
    priv = [r["intent"] for r in priv]

    started = time.time()

    # SELECT on DEV. PUBLIC is where a proposer would look; PRIVATE is untouched here.
    dev_scores = {
        name: score(arc, dev, cfg, args.budget, args.seeds)
        for name, cfg in CANDIDATES.items()
    }
    selected = max(dev_scores, key=lambda k: (dev_scores[k]["acc"], -list(CANDIDATES).index(k)))

    # PRIVATE scored ONCE: baseline and the selected candidate only.
    base_priv = score(arc, priv, CANDIDATES[BASELINE], args.budget, args.seeds)
    sel_priv = score(arc, priv, CANDIDATES[selected], args.budget, args.seeds)
    trans = transitions(base_priv["rows"], sel_priv["rows"])

    verdict = decide(
        gen0_priv_acc=base_priv["acc"],
        sel_priv_acc=sel_priv["acc"],
        sel_priv_correct=sel_priv["correct"],
        gen0_priv_correct=base_priv["correct"],
        trans=trans,
        private_n=base_priv["n"],
        gaming_hits=[],
    )

    result = {
        "budget": args.budget,
        "seeds": args.seeds,
        "salt": args.salt,
        "split": {"public": pub, "dev": dev, "private": priv},
        "split_sizes": {"public": len(pub), "dev": len(dev), "private": len(priv)},
        "dev_selection": {k: {"acc": round(v["acc"], 4), "levels": v["levels"]}
                          for k, v in dev_scores.items()},
        "selected": selected,
        "baseline": BASELINE,
        "private_n": base_priv["n"],
        "gen0_private_acc": round(base_priv["acc"], 4),
        "gen0_private_correct": base_priv["correct"],
        "selected_private_acc": round(sel_priv["acc"], 4),
        "selected_private_correct": sel_priv["correct"],
        "private_transitions": trans,
        "decision": verdict,
        "wall_clock_s": round(time.time() - started, 1),
    }

    payload = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
