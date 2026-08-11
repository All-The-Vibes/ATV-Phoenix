"""Score the fair runs against the published human baseline. Offline, zero API spend."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.rhae import score_game  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "eval" / "arc-results"


def main() -> int:
    logging.disable(logging.INFO)
    try:
        import arc_agi

        baselines = {
            e.game_id.split("-")[0]: list(e.baseline_actions or [])
            for e in arc_agi.Arcade().get_environments()
        }
        human = baselines.get("sb26") or []
    except Exception as exc:  # noqa: BLE001 - reporting, not control flow
        print(f"could not fetch baselines ({exc})")
        human = []

    if not human:
        print("no published baseline for sb26; cannot score")
        return 1

    print(f"human baseline sb26: {human}\n")
    for name in sys.argv[1:] or ["rulegate-run16", "fair-run1", "fair-run2", "fair-run3"]:
        path = ROOT / f"{name}.json"
        if not path.exists():
            continue
        run = json.loads(path.read_text(encoding="utf-8"))["runs"][0]
        score = score_game(
            "sb26",
            run["levels_completed"],
            human,
            ai_actions_per_level=run.get("level_actions"),
            ai_actions_total=run["actions_spent"],
        )
        print(f"{name:<16} {run['levels_completed']}/8  "
              f"actions={run['actions_spent']:<5} deaths={run['deaths']:<2} "
              f"RHAE={round(score.game_score * 100, 2)}%")
        print(f"{'':<16} per level: {run.get('level_actions')}")
        print(f"{'':<16} level scores: {[round(s, 3) for s in score.level_scores]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
