"""Score an ARC-AGI-3 run the way ARC scores it (issue #177).

Everything measured today counted levels completed, which is not the benchmark's metric.
ARC-AGI-3 uses Relative Human Action Efficiency (RHAE), specified at
https://docs.arcprize.org/methodology.md:

    level_score = min(1.15, (human_baseline_actions / ai_actions) ** 2)
    game_score  = sum(level_index * level_score) / sum(1 .. total_levels)
    total       = mean(game_score across all games)

Three consequences that matter and were invisible while counting levels:

**Efficiency is squared.** Twice the human action count scores 25 percent, not 50. Ten
times scores 1 percent. Completing a level slowly is worth almost nothing.

**The denominator is every level, not the ones you finished.** A game with 8 levels has a
weight sum of 36, so clearing level 1 perfectly caps that game at 1/36, or 2.8 percent.
Finishing the last level is the only way to unlock a full game score.

**Probe actions count.** The methodology counts any input that affects the game state.
The mechanical prober presses buttons, so its 625 actions on sb26 are charged to the run.
With a human baseline of 22 actions for level 1, a 9-action solve behind a 625-action
probe scores (22/634)^2, which is 0.1 percent rather than 100. The probe buys completion
and destroys efficiency, and nothing in the level count showed that trade.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

MAX_LEVEL_SCORE = 1.15


@dataclass
class GameScore:
    game: str
    levels_completed: int
    total_levels: int
    ai_actions: int
    human_actions: list[int]
    level_scores: list[float] = field(default_factory=list)
    game_score: float = 0.0
    max_possible: float = 0.0


def score_game(
    game: str,
    levels_completed: int,
    human_actions: list[int],
    ai_actions_per_level: list[int] | None = None,
    ai_actions_total: int | None = None,
) -> GameScore:
    """RHAE for one game.

    `ai_actions_per_level` is preferred. When only a run total is known, it is split
    evenly across the completed levels, which is the honest reading of an
    unattributed total: it neither flatters nor penalises any single level.
    """
    total_levels = len(human_actions)
    weight_sum = sum(range(1, total_levels + 1)) or 1

    if ai_actions_per_level is None:
        per_level = (
            [max(1, (ai_actions_total or 0) // max(1, levels_completed))] * levels_completed
            if levels_completed
            else []
        )
    else:
        per_level = ai_actions_per_level[:levels_completed]

    level_scores = []
    weighted = 0.0
    for index, spent in enumerate(per_level, start=1):
        baseline = human_actions[index - 1] if index <= len(human_actions) else 1
        raw = (baseline / max(1, spent)) ** 2
        score = min(MAX_LEVEL_SCORE, raw)
        level_scores.append(round(score, 4))
        weighted += index * score

    completed_weight = sum(range(1, levels_completed + 1))
    return GameScore(
        game=game,
        levels_completed=levels_completed,
        total_levels=total_levels,
        ai_actions=ai_actions_total or sum(per_level),
        human_actions=human_actions,
        level_scores=level_scores,
        game_score=round(weighted / weight_sum, 6),
        max_possible=round(completed_weight / weight_sum, 6),
    )


def score_run(results: list[dict], baselines: dict[str, list[int]]) -> dict:
    """RHAE across a corpus run.

    `results` is a list of per-game dicts carrying game, levels_completed and
    actions_spent, and optionally `level_actions`: the actions charged to each level
    separately. Per-level attribution is what the official scorer uses, since each
    level is scored on the actions spent on THAT level alone. A run total forces the
    even-split fallback, which charges level 1 for actions spent long after it was
    cleared and drags the whole game score down. `baselines` maps a game id to its
    per-level human action counts, which the ARC API publishes as `baseline_actions`.
    """
    scored = []
    for run in results:
        game = run["game"]
        human = baselines.get(game)
        if not human:
            continue
        per_level = run.get("level_actions") or None
        scored.append(
            score_game(
                game,
                run.get("levels_completed", 0),
                human,
                ai_actions_per_level=per_level,
                ai_actions_total=run.get("actions_spent", 0),
            )
        )

    total = sum(s.game_score for s in scored) / len(scored) if scored else 0.0
    completion_cap = sum(s.max_possible for s in scored) / len(scored) if scored else 0.0

    return {
        "rhae_total": round(total, 6),
        "rhae_percent": round(total * 100, 4),
        "completion_cap_percent": round(completion_cap * 100, 4),
        "games_scored": len(scored),
        "levels_completed": sum(s.levels_completed for s in scored),
        "levels_available": sum(s.total_levels for s in scored),
        "games": [
            {
                "game": s.game,
                "levels": f"{s.levels_completed}/{s.total_levels}",
                "ai_actions": s.ai_actions,
                "human_actions_for_completed": sum(s.human_actions[: s.levels_completed]),
                "game_score_percent": round(s.game_score * 100, 4),
                "capped_at_percent": round(s.max_possible * 100, 4),
            }
            for s in sorted(scored, key=lambda g: -g.game_score)
        ],
    }


def load_baselines() -> dict[str, list[int]]:
    """Per-level human action counts, straight from the ARC API metadata."""
    import arc_agi

    arc = arc_agi.Arcade()
    return {
        meta.game_id.split("-")[0]: list(meta.baseline_actions or [])
        for meta in arc.get_environments()
    }


def load_results(results_dir: Path) -> list[dict]:
    runs = []
    for path in sorted(results_dir.glob("mission-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        runs.extend(payload.get("runs", []))
    return runs


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    results = load_results(root / "eval" / "arc-results")
    if not results:
        print("no run results found")
        return 1

    report = score_run(results, load_baselines())
    print(json.dumps(report, indent=2))

    out = root / "eval" / "arc-results" / "rhae.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nRHAE {report['rhae_percent']}%  "
          f"(prime-agent reports 95.5%, human expert baseline 95.4%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
