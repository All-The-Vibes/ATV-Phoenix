"""Rebuild a scorecard for a run that died without writing one.

`play()` now checkpoints its scorecard every turn, so a run interrupted today
leaves a result behind. Runs started before that fix are executing the old code
from memory, and three of them were mid-flight when the fix landed: killing them
would have destroyed the only record they were ever played. The trace survives
every such event, because it is appended per turn; the scorecard did not, because
it was written once on a path that only a returning run ever reached.

So the trace is a second, independent record of the same run, and everything the
scorer needs is recoverable from it. This reads that record back out.

What is exact: levels completed, total actions, deaths, turns used. Those are
recorded per turn and simply read off the last row.

What is approximate, and why it still matters: `level_actions` -- the actions
charged to each level separately. The trace records a cumulative action count per
TURN, not per action, so a turn that clears a level attributes that whole turn's
actions to the level it was working on. The boundary can be off by the actions a
turn spent after the clear. It is reconstructed anyway because the alternative is
worse: `score_run` falls back to an even split when `level_actions` is missing,
which charges level 1 for actions spent long after level 1 was cleared and drags
the whole game score down. An approximate attribution is much closer to the truth
than a deliberately wrong one.

Every rescued scorecard is stamped `stopped: "rescued_from_trace"` and carries
`rescued: true`, so a rescued number can always be told apart from a run that
finished on its own.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.rhae import load_baselines  # noqa: E402

RESULTS = Path(__file__).resolve().parents[2] / "eval" / "arc-results"


def _rows(trace: Path) -> list[dict]:
    rows = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # A run killed mid-write leaves a torn final line. Every whole line
            # before it is still good, so keep them rather than losing the run.
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _game_for(run: str, baselines: dict[str, list[int]]) -> str | None:
    """Map a run name like 'lp85-c' to its game id.

    Matched against the real baseline ids rather than split on '-', so a run name
    that does not correspond to a game is reported instead of silently scored.
    """
    candidates = [g for g in baselines if run.startswith(g)]
    return max(candidates, key=len) if candidates else None


def rescue(run: str, baselines: dict[str, list[int]]) -> dict | None:
    trace = RESULTS / f"trace-{run}.jsonl"
    if not trace.exists():
        print(f"{run}: no trace at {trace.name}")
        return None

    rows = _rows(trace)
    if not rows:
        print(f"{run}: trace has no readable rows")
        return None

    game = _game_for(run, baselines)
    if game is None:
        print(f"{run}: no baseline game id matches this run name")
        return None

    last = rows[-1]
    levels = int(last.get("levels", 0))
    total_actions = int(last.get("total_actions", 0))
    deaths = sum(json.dumps(r).count("YOU DIED") for r in rows)

    # Attribute actions to the level that was being worked on when they were spent.
    per_level: dict[int, int] = {}
    prev_total = 0
    prev_levels = 0
    for row in rows:
        cur_total = int(row.get("total_actions", prev_total))
        cur_levels = int(row.get("levels", prev_levels))
        spent = max(0, cur_total - prev_total)
        cleared = max(0, cur_levels - prev_levels)
        if cleared > 1:
            # More than one level fell in a single turn; split that turn's actions
            # evenly across them rather than charging them all to the first.
            share, extra = divmod(spent, cleared)
            for i in range(cleared):
                per_level[prev_levels + i] = per_level.get(prev_levels + i, 0) + share + (
                    extra if i == cleared - 1 else 0
                )
        else:
            per_level[prev_levels] = per_level.get(prev_levels, 0) + spent
        prev_total, prev_levels = cur_total, cur_levels

    level_actions = [per_level.get(i, 0) for i in range(levels)]

    return {
        "agent": "gpt-5.6-sol",
        "auth": "managed_identity",
        "action_space": "executable_python",
        "games": 1,
        "levels_completed": levels,
        "levels_available": len(baselines[game]),
        "rescued": True,
        "runs": [
            {
                "game": game,
                "agent": "gpt-5.6-sol",
                "levels_completed": levels,
                "win_levels": len(baselines[game]),
                "actions_spent": total_actions,
                "level_actions": level_actions,
                "deaths": deaths,
                "seed": 0,
                "stopped": "rescued_from_trace",
                "turns_used": int(last.get("turn", len(rows))),
                "mechanics_learned": last.get("mechanics", []),
                "start_level": 1,
                "scorable": True,
                "rescued": True,
                "rescue_note": (
                    "Rebuilt from the per-turn trace after the run was interrupted "
                    "without writing a scorecard. level_actions is attributed at turn "
                    "granularity and may be off by the actions a level-clearing turn "
                    "spent after the clear."
                ),
            }
        ],
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m evals.arc.rescue <run> [<run> ...]")
        return 2

    baselines = load_baselines()
    written = 0
    for run in argv:
        card = rescue(run, baselines)
        if card is None:
            continue
        out = RESULTS / f"{run}.json"
        if out.exists():
            print(f"{run}: {out.name} already exists, refusing to overwrite")
            continue
        tmp = out.with_suffix(".json.partial")
        tmp.write_text(json.dumps(card, indent=2), encoding="utf-8")
        tmp.replace(out)
        r = card["runs"][0]
        print(
            f"{run}: rescued {r['game']} {r['levels_completed']}/{r['win_levels']} "
            f"acts={r['actions_spent']} deaths={r['deaths']} "
            f"level_actions={r['level_actions']} -> {out.name}"
        )
        written += 1

    print(f"\n{written} scorecard(s) rescued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
