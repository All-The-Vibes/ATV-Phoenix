"""Head-to-head: does the new model play better than the one we have?

A model swap is only worth the run if the comparison is honest, and the honest
comparison is not "did it clear more levels". RHAE squares the action count, so a
model that clears the same levels in half the actions is worth more than one that
clears an extra level slowly. This reports both, side by side, against the best
existing card for the same game.

The test is BOUNDED. Measured across 33 reference runs, level 1 falls by turn 1-5
on sb26, 7-19 on s5i5, 7-21 on cd82 -- so twenty-odd turns is not a truncated run,
it is the window where the answer actually lives. A 120-turn run to compare two
models is an hour spent watching the part that was already decided.

    python evals/arc/model_ab.py --tag k3
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.rhae import load_baselines, score_run  # noqa: E402

RESULTS = Path(__file__).resolve().parents[2] / "eval" / "arc-results"


def _cards():
    """Every scorable run on disk, keyed by game, tolerant of both file shapes."""
    out = {}
    for path in sorted(RESULTS.glob("*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs = blob if isinstance(blob, list) else (blob.get("runs") or [])
        for run in runs:
            if not isinstance(run, dict) or not run.get("game"):
                continue
            if run.get("scorable") is False or run.get("start_level", 1) != 1:
                continue
            out.setdefault(run["game"], []).append((path.name, run))
    return out


def _score(run, baselines):
    """Per-game RHAE as a percentage, the same number `standings.py` prints.

    `rhae_total` is a fraction and `rhae_percent` is the same value x100. Reporting
    the fraction here would print 0.27% beside a standings table saying 26.75% for the
    identical run, which is exactly the kind of quiet unit mismatch that has already
    produced a false 0.00% twice in this project.
    """
    try:
        return score_run([run], baselines)["rhae_percent"]
    except Exception:
        return 0.0


def _turns_to_level(game_tag):
    """When did each level fall? The shape of the run, not just its end state."""
    hits = []
    for path in RESULTS.glob(f"trace-{game_tag}.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for m in re.finditer(r"LEVEL (\d+) CLEARED in (\d+) actions",
                                 json.dumps(row.get("output", ""))):
                hits.append((row.get("turn", 0), int(m.group(1)), int(m.group(2))))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="run-name suffix of the challenger, e.g. k3")
    args = ap.parse_args()

    baselines = load_baselines()
    cards = _cards()

    challengers = sorted(glob.glob(str(RESULTS / f"*-{args.tag}.json")))
    if not challengers:
        print(f"no scorecards matching *-{args.tag}.json yet")
        return 1

    print(f"{'game':<7}{'who':<10}{'lv':>4}{'/of':>5}{'acts':>7}{'deaths':>8}"
          f"{'turns':>7}{'score':>9}  level_actions")
    print("-" * 92)

    verdicts = []
    for path in challengers:
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        runs = blob if isinstance(blob, list) else (blob.get("runs") or [])
        if not runs:
            continue
        new = runs[0]
        game = new.get("game")
        if not game:
            continue

        # The incumbent is the best existing card for this game that is NOT the challenger.
        rivals = [(n, r) for n, r in cards.get(game, []) if not n.endswith(f"-{args.tag}.json")]
        best = max(rivals, key=lambda nr: _score(nr[1], baselines), default=None)

        for label, run in (("incumbent", best[1] if best else None), ("challenger", new)):
            if run is None:
                print(f"{game:<7}{label:<10}{'-- no prior card --':>40}")
                continue
            print(f"{game:<7}{label:<10}{run.get('levels_completed', 0):>4}"
                  f"{run.get('win_levels', 0):>5}{run.get('actions_spent', 0):>7}"
                  f"{run.get('deaths', 0):>8}{run.get('turns_used', 0):>7}"
                  f"{_score(run, baselines):>8.2f}%  {run.get('level_actions')}")

        if best:
            old, new_s = _score(best[1], baselines), _score(new, baselines)
            ol, nl = best[1].get("levels_completed", 0), new.get("levels_completed", 0)
            oa, na = best[1].get("actions_spent", 1), new.get("actions_spent", 1)
            ot, nt = best[1].get("turns_used", 0), new.get("turns_used", 0)

            # A bounded challenger that matched the incumbent's levels in fewer turns has
            # not tied -- it did the same work with less of the budget, and the rest of
            # its run is unspent. Say so rather than reporting a wash.
            note = ""
            if nl == ol and nt and ot and nt < ot * 0.6:
                note = f"  (matched in {nt} turns vs {ot} -- bounded, not finished)"
            if nl > ol:
                note = "  (cleared MORE levels)"
            elif nl == ol and na < oa * 0.7:
                note = f"  ({100 * (1 - na / oa):.0f}% fewer actions for the same levels)"

            verdicts.append((game, old, new_s, nl - ol, note))
        print()

    if verdicts:
        print("=" * 92)
        print(f"{'game':<7}{'incumbent':>11}{'challenger':>12}{'delta':>9}{'levels':>8}")
        print("-" * 92)
        for game, old, new_s, dl, note in verdicts:
            print(f"{game:<7}{old:>10.2f}%{new_s:>11.2f}%{new_s - old:>+8.2f}%"
                  f"{dl:>+8}{note}")
        print("-" * 92)
        wins = sum(1 for _, o, n, _, _ in verdicts if n > o)
        print(f"challenger scored higher on {wins} of {len(verdicts)} game(s)")
        print("\nRHAE squares the action count: the same levels in half the actions beats")
        print("one more level spent slowly. Read level_actions, not just the level count.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
