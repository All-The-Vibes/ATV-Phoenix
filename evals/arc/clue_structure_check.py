"""Does the clue row's shape reach the agent correctly on every level? Offline, free.

Level 5 draws nine rings over eight pads and the agent read them as a flat list, got a
contradiction, and spent the level guessing. `parse()` now reports the row's shape. This
checks that report against every level the harness can reach: flat where the row really is
one ring per pad, and the right block where it is not.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import arc_agi  # noqa: E402

from evals.arc.codeact_agent import Env, LevelCleared  # noqa: E402
from evals.arc.frames import parse, plan  # noqa: E402

# What the row is drawn as, read off the board by hand. Level 5 is the one that is not
# flat: `6,[14,8,8],[14,8,8],11,15` over eight pads.
EXPECTED = {
    5: {"flat": False, "block": [14, 8, 8], "reduced": [6, None, None, 11, 15],
        "rows": 1, "cols": 9},
    # Level 7 goes the other way: SEVEN rings over EIGHT pads, a palindrome over three
    # sibling frames. No block decomposition explains a short row, but calling it flat
    # would be the same lie that cost eleven runs on level 5.
    7: {"flat": False, "block": None, "reduced": [8, 9, 14, 11, 14, 9, 8],
        "rows": 1, "cols": 7},
    # Level 8 is the third shape: TWELVE rings over EIGHT pads, drawn as two rows of six
    # where the second row restates the first. Flattened it reads
    # 8,8,11,11,12,12,9,9,14,14,15,15 and the doubling is indistinguishable from a tray
    # holding two of something -- measured, the agent fused the two and searched a rank
    # of eight it had invented. Collapsed, it is a six-colour row over eight pads.
    8: {"flat": False, "block": None, "reduced": [8, 11, 12, 9, 14, 15],
        "rows": 2, "cols": 6},
}


def check_by_jump(levels=range(1, 9)) -> bool:
    """Verify the clue report on EVERY level, including the ones the planner cannot reach.

    The walk below stops where the planner stops, which is level 6, so levels 7 and 8
    were never actually checked by this file -- their expectations sat in EXPECTED and
    were never compared against anything. Jumping straight to a level costs no actions
    and no tokens, so there is no reason for the two hardest boards to be the two that
    go unverified.
    """
    from evals.arc.level_jump import make_at_level

    ok = True
    for level in levels:
        raw, frame, _ = make_at_level("sb26", level, 0)
        env = Env(raw, frame, inert_limit=10_000, death_limit=10_000,
                  turn_action_cap=100_000)
        L = parse(env.grid())
        if not L:
            print(f"FAIL  level {level}: does not parse")
            ok = False
            continue
        s = L["clue_structure"]
        grid = s["grid"]
        want = EXPECTED.get(level)
        if want is None:
            want = {"flat": True, "block": None,
                    "reduced": list(s["colours"]), "rows": 1,
                    "cols": len(L["pads"])}
            good = s["flat"] and len(s["colours"]) == len(L["pads"])
        else:
            good = (s["flat"] == want["flat"] and s["block"] == want["block"]
                    and s["reduced"] == want["reduced"])
        good = good and grid["rows"] == want["rows"] and grid["cols"] == want["cols"]
        # Collapsing must never invent or lose a ring.
        good = good and grid["rows"] * grid["cols"] == len(grid["drawn"])
        print(f"{'PASS' if good else 'FAIL'}  level {level}: {len(grid['drawn'])} rings "
              f"drawn {grid['rows']}x{grid['cols']} over {len(L['pads'])} pads "
              f"-> {s['colours']}")
        if not good:
            print(f"        wanted flat={want['flat']} block={want['block']} "
                  f"reduced={want['reduced']} {want['rows']}x{want['cols']}")
        ok = ok and good
    return ok


def main(max_levels=7) -> int:
    arc = arc_agi.Arcade()
    raw = arc.make("sb26", include_frame_data=True)
    env = Env(raw, raw.reset(), inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)

    ok = True
    level = 0
    while level < max_levels:
        level = env.levels() + 1
        L = parse(env.grid())
        if not L:
            print(f"level {level}: does not parse")
            return 1
        s = L["clue_structure"]
        want = EXPECTED.get(level)

        if want is None:
            # No hand-read expectation: the row should be flat and one ring per pad.
            good = s["flat"] and len(s["colours"]) == len(L["pads"])
            print(f"{'PASS' if good else 'FAIL'}  level {level}: flat row, "
                  f"{len(s['colours'])} rings over {len(L['pads'])} pads")
        else:
            good = (s["flat"] == want["flat"] and s["block"] == want["block"]
                    and s["reduced"] == want["reduced"])
            print(f"{'PASS' if good else 'FAIL'}  level {level}: "
                  f"{len(s['colours'])} rings over {len(L['pads'])} pads, "
                  f"block={s['block']} reduced={s['reduced']}")
            if not good:
                print(f"        wanted block={want['block']} "
                      f"reduced={want['reduced']} flat={want['flat']}")

        # The structure has to be enough to reach the winning assignment: the reduced row
        # plus the block must account for the tray exactly once the hole is filled.
        if not s["flat"] and s["block"]:
            tray = sorted(t["colour"] for t in L["tray"])
            spelled = [c for c in s["reduced"] if c is not None] + s["block"]
            holes = sum(1 for c in s["reduced"] if c is None)
            left = sorted(tray)
            for c in spelled:
                if c in left:
                    left.remove(c)
            fills = set(left)
            enough = len(left) == holes and len(fills) == 1
            print(f"        {'PASS' if enough else 'FAIL'}  the tray leaves exactly "
                  f"{holes} pieces for {holes} hole(s): {sorted(left)}")
            ok = ok and enough

        ok = ok and good

        try:
            steps = plan(env.grid())
            if not steps:
                # The planner stops at level 6. That is fine: this file is checking what
                # the agent is TOLD about the row, not whether the harness can solve it.
                print(f"        (planner has no answer for level {level}; "
                      f"stopping the walk here)")
                break
            pool = list(L["tray"])
            for colour, pad in steps:
                src = next(t for t in pool if t["colour"] == colour)
                pool.remove(src)
                env.click(src["cx"], src["cy"])
                env.click(*pad)
            env.press(5)
        except LevelCleared:
            try:
                env.press(7)
            except LevelCleared:
                pass
            continue
        break

    print()
    print("every level, jumped (the planner stops at 6, these do not):")
    ok = check_by_jump() and ok

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
