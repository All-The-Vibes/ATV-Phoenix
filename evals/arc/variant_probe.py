"""Does level 8's answer depend on WHICH piece of a colour is used? Offline, no model.

Level 8's tray holds two 8s and two 9s, and in each pair one piece is SOLID and one is
HOLLOW. Every other colour appears once. Measured consequence: the colour arrangement
`8,11,12,9 / 9,14,15,8` cleared the level in a debug session and was submitted twice in a
full run WITHOUT clearing it. A colour map cannot be both winning and losing, so the
answer must distinguish the two pieces that share a colour.

This settles it without spending a model call: build that one colour arrangement four
times, once per choice of which 8 and which 9 goes on top, and report which of the four
the game accepts. If exactly one wins, `try_assignment`'s colour->pad interface is not
expressive enough to state the answer, which is a harness bug and not a reasoning one.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.codeact_agent import Env, LevelCleared  # noqa: E402
from evals.arc.frames import parse  # noqa: E402
from evals.arc.level_jump import make_at_level  # noqa: E402

TOP = [(22, 26), (28, 26), (34, 26), (40, 26)]
BOTTOM = [(22, 40), (28, 40), (34, 40), (40, 40)]
TOP_COLOURS = [8, 11, 12, 9]
BOTTOM_COLOURS = [9, 14, 15, 8]


def _is_hollow(piece) -> bool:
    w = piece["x1"] - piece["x0"] + 1
    h = piece["y1"] - piece["y0"] + 1
    return int(piece["px"]) < w * h


def _grab_point(piece):
    """A pixel that is certainly ON the piece.

    A hollow piece's centre is its hole, and clicking the hole does not pick the piece
    up -- measured on level 7, where every placement of the last two pieces silently did
    nothing. The top-left corner of the bounding box is on the drawn border either way.
    """
    return (int(piece["x0"]), int(piece["y0"])) if _is_hollow(piece) else (
        int(piece["cx"]), int(piece["cy"]))


def attempt(top_eight_hollow: bool, top_nine_hollow: bool) -> tuple[bool, str]:
    raw, frame, _ = make_at_level("sb26", 8, 0)
    env = Env(raw, frame, inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)
    layout = parse(env.grid())
    if not layout:
        return False, "board did not parse"

    pool = list(layout["tray"])

    def take(colour: int, want_hollow: bool | None):
        matches = [p for p in pool if int(p["colour"]) == colour]
        if want_hollow is not None:
            picked = next((p for p in matches if _is_hollow(p) == want_hollow), None)
        else:
            picked = matches[0] if matches else None
        if picked is None:
            raise LookupError(f"no piece colour={colour} hollow={want_hollow}")
        pool.remove(picked)
        return picked

    plan = []
    for colour, pad in zip(TOP_COLOURS, TOP):
        want = top_eight_hollow if colour == 8 else (
            top_nine_hollow if colour == 9 else None)
        plan.append((take(colour, want), pad))
    for colour, pad in zip(BOTTOM_COLOURS, BOTTOM):
        want = (not top_eight_hollow) if colour == 8 else (
            (not top_nine_hollow) if colour == 9 else None)
        plan.append((take(colour, want), pad))

    try:
        for piece, pad in plan:
            env.click(*_grab_point(piece))
            env.click(*pad)
        env.press(5)
    except LevelCleared:
        return True, "CLEARED"
    return False, f"rejected (levels={env.levels()})"


def via_try_assignment(top_eight: str, top_nine: str) -> tuple[bool, str]:
    """The same four attempts, but stated through `try_assignment`'s qualified colours.

    The point of the qualifier is that the agent can reach this outcome without hand-
    placing anything, so it is checked through the interface the agent actually uses.
    """
    raw, frame, _ = make_at_level("sb26", 8, 0)
    env = Env(raw, frame, inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)
    other = {"solid": "hollow", "hollow": "solid"}
    mapping = [((8, top_eight), TOP[0]), (11, TOP[1]), (12, TOP[2]),
               ((9, top_nine), TOP[3]),
               ((9, other[top_nine]), BOTTOM[0]), (14, BOTTOM[1]), (15, BOTTOM[2]),
               ((8, other[top_eight]), BOTTOM[3])]
    try:
        result = env.try_assignment(mapping)
    except LevelCleared:
        return True, "CLEARED"
    return bool(result.get("won")), (
        "CLEARED" if result.get("won")
        else f"rejected (ok={result.get('ok')}, levels={env.levels()})")


def main() -> int:
    print("level 8, colour arrangement 8,11,12,9 / 9,14,15,8 -- the one measured both "
          "winning and losing.")
    print("varying only WHICH piece of each doubled colour goes on the top row:\n")
    wins = []
    for eight_hollow in (False, True):
        for nine_hollow in (False, True):
            ok, why = attempt(eight_hollow, nine_hollow)
            label = (f"top 8 = {'hollow' if eight_hollow else 'solid '}, "
                     f"top 9 = {'hollow' if nine_hollow else 'solid '}")
            print(f"  {'WIN ' if ok else 'lose'}  {label}   {why}")
            if ok:
                wins.append((eight_hollow, nine_hollow))

    print()
    if len(wins) != 1:
        if not wins:
            print("NONE of the four won: the colour arrangement itself is wrong.")
        else:
            print(f"{len(wins)} of four won, so solid/hollow is not the whole story.")
        return 1

    e, n = wins[0]
    print("EXACTLY ONE of four wins on an identical colour map, so the answer is not a "
          "colour map.")
    print(f"  the winning one puts the {'hollow' if e else 'solid'} 8 and the "
          f"{'hollow' if n else 'solid'} 9 on the top row.")

    print("\nand the agent can now SAY that through try_assignment's qualified colours:")
    ok, why = via_try_assignment("hollow" if e else "solid",
                                 "hollow" if n else "solid")
    print(f"  {'PASS' if ok else 'FAIL'}  try_assignment with (colour, 'solid'/'hollow') "
          f"reaches the winning board: {why}")
    if not ok:
        return 1

    # And the qualifier has to be load-bearing: a wrong one must still lose, or it is
    # being ignored rather than honoured.
    ok_wrong, why_wrong = via_try_assignment("solid" if e else "hollow",
                                             "hollow" if n else "solid")
    print(f"  {'PASS' if not ok_wrong else 'FAIL'}  and the WRONG qualifier still loses, "
          f"so it is honoured rather than ignored: {why_wrong}")
    return 0 if not ok_wrong else 1


if __name__ == "__main__":
    raise SystemExit(main())
