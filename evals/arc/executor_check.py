"""Does try_assignment play a hypothesis for the fewest cells? Plays the real game.

The bind this exists to remove. A hypothesis built from scratch costs one cell per drop
plus one to submit -- nine on an eight-pad level -- so a 64-cell bar funds seven per life.
Level 7 has 8!/(2!3!3!) = 560 candidate assignments, and measured runs were spending 84
actions per hypothesis against a floor of 17, because every new candidate tore the board
down and rebuilt it.

Three mechanics measured against the live game make that unnecessary:

    lift a piece already ON a pad ..... 0 cells
    drop onto an OCCUPIED pad ......... 1 cell, and it SWAPS the two pieces
    undo ............................. 0 cells

Every candidate is a permutation of the same tray, so one can be turned into another by
swaps alone. This check proves the executor exploits that: a second hypothesis differing
on two pads must cost far less than a rebuild.

Fails on the parent commit -- `seated` and `try_assignment` do not exist there.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from evals.arc.codeact_agent import Env  # noqa: E402
from evals.arc.frames import parse  # noqa: E402


def main() -> int:
    import arc_agi

    ok = True
    raw = arc_agi.Arcade().make("sb26", include_frame_data=True)
    env = Env(raw, raw.reset(), turn_action_cap=4000)

    layout = parse(env.grid())
    pads = sorted(layout["pads"], key=lambda p: (p["cy"], p["cx"]))
    tray = sorted(layout["tray"], key=lambda t: (t["cx"], t["cy"]))
    coords = [(int(p["cx"]), int(p["cy"])) for p in pads]
    colours = [int(t["colour"]) for t in tray]
    print(f"level 1: {len(pads)} pads, tray {colours}, bar {env.clock()['left']}")

    # An empty board must read as empty, or the executor's first pass is blind.
    start = env.seated()
    good = all(v is None for v in start.values()) and len(start) == len(pads)
    print(f"{'PASS' if good else 'FAIL'}  seated() reads an untouched board as empty "
          f"({sum(v is None for v in start.values())}/{len(start)} pads empty)")
    ok = ok and good

    # ── first hypothesis: a full build ───────────────────────────────────────────────
    first = dict(zip(coords, colours))
    before = env.clock()["left"]
    result = env.try_assignment(first)
    build_cost = before - env.clock()["left"]
    good = result["ok"]
    print(f"{'PASS' if good else 'FAIL'}  a first hypothesis is achieved "
          f"(cost {build_cost} cells)")
    ok = ok and good

    good = env.seated() == first
    print(f"{'PASS' if good else 'FAIL'}  the board really holds what was asked for")
    ok = ok and good

    # ── second hypothesis: two pads swapped ──────────────────────────────────────────
    # Chosen so exactly two pads differ, which is the common case when walking a
    # candidate list in a sensible order.
    second = dict(first)
    a, b = coords[0], coords[1]
    second[a], second[b] = first[b], first[a]

    before = env.clock()["left"]
    result = env.try_assignment(second)
    swap_cost = before - env.clock()["left"]

    good = result["ok"] and env.seated() == second
    print(f"{'PASS' if good else 'FAIL'}  a two-pad change is achieved "
          f"(cost {swap_cost} cells)")
    ok = ok and good

    good = swap_cost < build_cost
    print(f"{'PASS' if good else 'FAIL'}  it costs less than a rebuild "
          f"({swap_cost} < {build_cost})")
    ok = ok and good

    # The whole point: on an N-pad level a rebuild is N+1, and a two-pad change must be
    # nowhere near that or the search budget is unchanged.
    good = swap_cost <= 3
    print(f"{'PASS' if good else 'FAIL'}  and it costs at most 3 cells "
          f"(1 swap + 1 submit), got {swap_cost}")
    ok = ok and good

    hypotheses_per_life = 64 // max(1, swap_cost)
    rebuild_per_life = 64 // max(1, build_cost)
    print(f"        => {hypotheses_per_life} hypotheses per 64-cell life, "
          f"against {rebuild_per_life} by rebuilding")

    # ── a three-pad rotation, the other common case ──────────────────────────────────
    third = dict(second)
    if len(coords) >= 3:
        x, y, z = coords[0], coords[1], coords[2]
        third[x], third[y], third[z] = second[y], second[z], second[x]
        before = env.clock()["left"]
        result = env.try_assignment(third)
        rot_cost = before - env.clock()["left"]
        good = result["ok"] and env.seated() == third
        print(f"{'PASS' if good else 'FAIL'}  a three-pad rotation is achieved "
              f"(cost {rot_cost} cells)")
        ok = ok and good
        good = rot_cost < build_cost
        print(f"{'PASS' if good else 'FAIL'}  also cheaper than a rebuild "
              f"({rot_cost} < {build_cost})")
        ok = ok and good

    # ── and it must survive a HOLLOW piece ───────────────────────────────────────────
    #
    # The measured break. From level 4 the game draws some pieces as a ring with its
    # middle punched out, so the commonest colour inside the box is the HOLE, which reads
    # as the board background. On level 5 two pads holding c9 rings were reported empty,
    # the executor built an arrangement that was not the one it was asked for, and the
    # eight cells it spent bought nothing.
    #
    # Asserted against a crafted board rather than by playing forward to level 5, because
    # reaching that level requires solving levels 1-4 and this check must not depend on
    # the agent being right. A pad box is written by hand with a ring of piece colour
    # around a hole of background, which is exactly what the game draws.
    print("\nhollow piece, on a crafted board:")
    raw2 = arc_agi.Arcade().make("sb26", include_frame_data=True)
    probe = Env(raw2, raw2.reset(), turn_action_cap=10)
    probe.seated()  # learn geometry and the empty-pad colour from the pristine board
    board = probe.grid().copy()
    values, counts = np.unique(board, return_counts=True)
    background = int(values[np.argmax(counts)])
    pad = probe._pad_boxes[0]
    ring = 9
    # Background-dominant on purpose. A 4x4 box with a 2x2 hole still has more ring than
    # hole, so it would not exercise the bug; what broke on level 5 is a pad box whose
    # commonest colour is the background, and that is what is built here.
    board[pad["y0"]:pad["y1"] + 1, pad["x0"]:pad["x1"] + 1] = background
    board[pad["y0"], pad["x0"]] = ring
    board[pad["y1"], pad["x1"]] = ring

    class Frozen:
        frame = [board.tolist()]

    probe._frame = Frozen()
    reading = probe.seated()[(pad["cx"], pad["cy"])]
    good = reading == ring
    print(f"  {'PASS' if good else 'FAIL'}  ink of {ring} in a box dominated by "
          f"{background} reads as {reading}, expected {ring}")
    ok = ok and good

    patch = board[pad["y0"]:pad["y1"] + 1, pad["x0"]:pad["x1"] + 1]
    vals, cnts = np.unique(patch, return_counts=True)
    hole_majority = int(vals[np.argmax(cnts)])
    good = hole_majority == background
    print(f"  {'PASS' if good else 'FAIL'}  and the naive majority reading really would "
          f"have said {hole_majority} (that is the bug this replaces)")
    ok = ok and good

    # An empty pad must still read as empty, or the executor seats pieces it already has.
    probe2 = Env(*(lambda r: (r, r.reset()))(
        arc_agi.Arcade().make("sb26", include_frame_data=True)), turn_action_cap=10)
    empties = probe2.seated()
    good = all(v is None for v in empties.values())
    print(f"  {'PASS' if good else 'FAIL'}  an empty pad still reads as empty, not as "
          f"its own outline ({sum(v is None for v in empties.values())}/{len(empties)})")
    ok = ok and good

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
