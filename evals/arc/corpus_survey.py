"""Does this harness see ANY of the 25 ARC-AGI-3 games, or only sb26? Offline, free.

Everything measured so far is one game. `frames.parse` was written against sb26 and
tuned against sb26's eight levels, so the honest question before promising anything
corpus-wide is which other environments it can even describe.

This spends NO model calls and NO game actions: it opens each environment, reads the
first frame, and asks the parser what it sees. A game that does not parse is not
necessarily unwinnable -- it means the frames.py abstraction (frames / pads / clues /
tray) does not describe it, and the agent would be working from raw pixels there.

The output is a corpus map, not a score. Scores come from runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def survey() -> list[dict]:
    import arc_agi

    from evals.arc.boardread import objects as board_objects
    from evals.arc.frames import parse

    arc = arc_agi.Arcade()
    rows = []
    for meta in arc.get_environments():
        game = meta.game_id.split("-")[0]
        baseline = list(meta.baseline_actions or [])
        row = {
            "game": game,
            "levels": len(baseline),
            "human_actions": baseline,
            "human_total": sum(baseline),
        }
        try:
            env = arc.make(game, seed=0, include_frame_data=True)
            frame = env.reset()
            import numpy as np

            arr = np.array(frame.frame, dtype=np.int8)
            grid = arr[0] if arr.ndim == 3 else arr
            row["grid"] = f"{grid.shape[1]}x{grid.shape[0]}"
            row["blobs"] = len(board_objects(grid))
            layout = parse(grid)
            if layout:
                row["parses"] = True
                row["pads"] = len(layout["pads"])
                row["tray"] = len(layout["tray"])
                row["clues"] = len(layout["clues"])
                row["frames"] = len(layout["frames"])
                structure = layout["clue_structure"]["grid"]
                row["clue_grid"] = f"{structure['rows']}x{structure['cols']}"
                # `well_formed` is the parser's own precondition: one tray piece per pad.
                # Asked of an OPENING frame -- which is what this survey reads -- it is
                # the honest answer to "does this abstraction describe this game at all".
                row["sb26_shaped"] = bool(layout["well_formed"])
            else:
                row["parses"] = False
                row["sb26_shaped"] = False
            # And the strict parse must agree, or the flag and the refusal disagree about
            # the same board, which would be a new way to lie.
            row["strict_parses"] = parse(grid, strict=True) is not None
        except Exception as exc:  # noqa: BLE001 - a survey must not die on one game
            row["parses"] = False
            row["sb26_shaped"] = False
            row["error"] = f"{type(exc).__name__}: {exc}"[:120]
        rows.append(row)
    return rows


def main() -> int:
    rows = survey()
    parses = [r for r in rows if r.get("parses")]
    shaped = [r for r in rows if r.get("sb26_shaped")]

    print(f"{'game':10} {'lvls':>4} {'human':>6} {'grid':>9} {'blobs':>6} "
          f"{'parse':>6} {'pads':>5} {'tray':>5} {'clue':>6} {'sb26-shaped':>12}")
    for r in sorted(rows, key=lambda r: r["game"]):
        print(f"{r['game']:10} {r['levels']:>4} {r['human_total']:>6} "
              f"{r.get('grid',''):>9} {r.get('blobs',0):>6} "
              f"{'yes' if r.get('parses') else 'NO':>6} "
              f"{r.get('pads',''):>5} {r.get('tray',''):>5} "
              f"{r.get('clue_grid',''):>6} "
              f"{'yes' if r.get('sb26_shaped') else 'no':>12}")

    print()
    print(f"environments:        {len(rows)}")
    print(f"parse() describes:   {len(parses)}")
    print(f"sb26-shaped:         {len(shaped)}  "
          f"({', '.join(sorted(r['game'] for r in shaped))})")
    disagree = [r["game"] for r in rows
                if bool(r.get("strict_parses")) != bool(r.get("sb26_shaped"))]
    print(f"strict parse agrees: {'yes' if not disagree else 'NO -- ' + ', '.join(disagree)}")
    print()
    print("ARC scores the corpus as the MEAN game score over ALL games, so a game we")
    print("never play scores 0 and drags the total by its full share. One perfect game")
    print(f"out of {len(rows)} caps the total at {1.15/len(rows)*100:.2f}%.")

    out = Path(__file__).resolve().parents[2] / "eval" / "arc-results" / "corpus-survey.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
