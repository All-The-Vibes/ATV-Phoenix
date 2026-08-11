"""Can the agent see its life budget drain? On every game with a bar. Offline, free.

A death costs a whole bar. On cd82 that was measured at 74-83 actions apiece, six times in
one run: 463 of 713 actions, 65% of everything the run spent, on deaths the agent never saw
coming. `clock()` read a confident full bar on the fresh board and then returned every
field None from the first action onward, so there was no warning to act on.

The cause was an assumption imported from sb26, which draws its bar in colours reserved for
it: any row containing the board's background colour was disqualified from being the bar.
cd82 spends its bar INTO the background, so the row was rejected precisely when it started
carrying information.

This checks the thing that actually matters -- not that some number comes back, but that
the reading stays CONFIRMED and MONOTONE while actions are spent -- and it checks it on
more than one game, because proving a perception fix against a single game is what created
this bug in the first place.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def spend(env, presses: int):
    """Spend actions in whatever way this game charges for, and read the bar each time."""
    readings = []
    for i in range(presses):
        # Alternate two directional/among-available actions so the board keeps changing;
        # which action a game charges for is a per-game fact and not assumed here.
        action = env.actions[i % len(env.actions)]
        try:
            env.press(action)
        except Exception:  # noqa: BLE001 - a dead or finished level ends the sample
            break
        readings.append(env.clock())
    return readings


def check_game(game: str, presses: int = 12) -> bool:
    import arc_agi

    from evals.arc.codeact_agent import Env

    arc = arc_agi.Arcade()
    raw = arc.make(game, include_frame_data=True)
    env = Env(raw, raw.reset(), inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)

    opening = env.clock()
    ok = bool(opening and opening.get("confirmed"))
    print(f"  {'PASS' if ok else 'FAIL'}  {game}: the opening board shows a full bar "
          f"({opening.get('left')}/{opening.get('total')} "
          f"colour {opening.get('full_colour')})")
    if not ok:
        return False

    readings = [r for r in spend(env, presses) if r]
    if not readings:
        print(f"  FAIL  {game}: no readings after spending actions")
        return False

    confirmed = [r for r in readings if r.get("confirmed")]
    good = len(confirmed) == len(readings)
    print(f"  {'PASS' if good else 'FAIL'}  {game}: stayed readable while spending "
          f"({len(confirmed)}/{len(readings)} reads confirmed)")
    ok = ok and good

    lefts = [r.get("left") for r in confirmed if r.get("left") is not None]
    if lefts:
        monotone = all(b <= a for a, b in zip(lefts, lefts[1:]))
        moved = lefts[-1] < opening.get("total", 10**9)
        print(f"  {'PASS' if monotone else 'FAIL'}  {game}: never refills "
              f"({opening.get('total')} -> {lefts[-1]})")
        print(f"  {'PASS' if moved else 'FAIL'}  {game}: actually drains, so a warning "
              f"is possible before the bar runs out")
        ok = ok and monotone and moved

        # THE BAR MUST STAY THE SAME ROW, and this is the assertion that was missing when
        # it mattered. A first attempt at reading cd82's bar latched onto row 63 on the
        # opening board and then onto row 16 -- a static strip of board furniture drawn in
        # the same two colours -- for every read after it, reporting a FROZEN 18/64 for the
        # rest of the level. Every check above passed: a constant is monotone, and 18 is
        # less than 64, so it "drained". A frozen number is worse than no number, because
        # it looks like a reading. The bar does not move between frames; if the row does,
        # we are reading two different things and calling them one.
        rows = [r.get("row") for r in confirmed if r.get("row") is not None]
        settled = len(set(rows)) <= 1 and (not rows or rows[0] == opening.get("row"))
        print(f"  {'PASS' if settled else 'FAIL'}  {game}: reads the SAME row throughout "
              f"(opening {opening.get('row')}, then {sorted(set(rows))})")
        ok = ok and settled

        # And it must not sit still while actions are being spent, which is the other half
        # of the same bug: a reading that never changes is not tracking anything.
        varied = len(set(lefts)) > 1
        print(f"  {'PASS' if varied else 'FAIL'}  {game}: the reading actually CHANGES "
              f"while spending ({lefts[0]} ... {lefts[-1]})")
        ok = ok and varied
    else:
        print(f"  FAIL  {game}: confirmed reads carried no remaining count")
        ok = False
    return ok


def main() -> int:
    # sb26 is the regression guard: its bar uses reserved colours and must read exactly as
    # before. cd82 is the game the old reading went blind on.
    games = sys.argv[1:] or ["sb26", "cd82"]
    ok = True
    for game in games:
        print(f"\n{game}:")
        ok = check_game(game) and ok
    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
