"""Run ARC-AGI-3 environments under a policy and emit a JSON result (issue #177).

This is the meter, not a competitor. It answers one question per run: how many
levels did this policy complete, and how many actions did it spend against the
human baseline the environment publishes in ``baseline_actions``.

Usage::

    python -m evals.arc.run_arc --policy novelty --games sp80,cd82 --budget 2000
    python -m evals.arc.run_arc --policy null --all --budget 500 --out floor.json

Exit code is 0 when the run completes. Judging is the caller's job, which keeps
this script a measurement and lets ``phoenix_sense`` own the pass/fail.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.policies import Policy  # noqa: E402

TERMINAL = ("GameState.WIN", "GameState.GAME_OVER")


def play(arc, game: str, policy_name: str, budget: int, seed: int) -> dict:
    """Play one environment under one policy for a fixed action budget."""
    env = arc.make(game, include_frame_data=True)
    frame = env.reset()
    policy = Policy(policy_name, env.action_space, seed=seed)

    best = 0
    errors = 0
    started = time.time()
    for _ in range(budget):
        action, data = policy.act(frame)
        try:
            nxt = env.step(action, data) if data else env.step(action)
        except Exception:
            errors += 1
            continue
        if nxt is None:
            errors += 1
            continue
        frame = nxt
        best = max(best, frame.levels_completed)
        if str(frame.state) in TERMINAL:
            frame = env.reset()

    elapsed = time.time() - started
    return {
        "game": game,
        "policy": policy_name,
        "seed": seed,
        "levels_completed": best,
        "win_levels": frame.win_levels,
        "actions_spent": budget,
        "step_errors": errors,
        "elapsed_s": round(elapsed, 3),
        "fps": round(budget / elapsed, 1) if elapsed else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="novelty", choices=["null", "random", "novelty"])
    ap.add_argument("--games", default="", help="comma-separated game prefixes")
    ap.add_argument("--all", action="store_true", help="every available environment")
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import arc_agi

    arc = arc_agi.Arcade()
    available = [e.game_id.split("-")[0] for e in arc.get_environments()]

    if args.all:
        games = available
    elif args.games:
        games = [g.strip() for g in args.games.split(",") if g.strip()]
    else:
        games = available[:1]

    unknown = [g for g in games if g not in available]
    if unknown:
        print(f"unknown games: {unknown}", file=sys.stderr)
        return 2

    started = time.time()
    runs = [play(arc, g, args.policy, args.budget, args.seed) for g in games]
    result = {
        "policy": args.policy,
        "budget_per_game": args.budget,
        "seed": args.seed,
        "games": len(runs),
        "levels_completed": sum(r["levels_completed"] for r in runs),
        "levels_available": sum(r["win_levels"] for r in runs),
        "step_errors": sum(r["step_errors"] for r in runs),
        "wall_clock_s": round(time.time() - started, 3),
        "runs": runs,
    }

    payload = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
