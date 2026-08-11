"""Start a run on any level, for DEBUGGING THE HARNESS ONLY.

Reaching level 7 honestly costs about 215 actions and a dozen model calls -- roughly
eight minutes and 600,000 tokens before a single level-7 experiment begins. Paying that
on every iteration is what made the level-7 work slow today, and none of it was buying
information: levels 1 to 6 already fall reliably with zero deaths.

`arcengine`'s game object exposes `set_level(index)`, so a session can begin on level 7
directly. Two facts make this safe rather than a shortcut around the benchmark:

  * `levels_completed` stays at ZERO after a jump. The scorecard gives no credit for
    levels that were skipped, so a jumped session cannot inflate a score even
    deliberately. Verified: `set_level(6)` leaves `levels_completed == 0`.
  * It is a private engine method, not part of the ARC API surface, and Competition Mode
    routes everything through the API.

So this file exists to answer "does the HARNESS work on level 7" -- does the executor
reach the arrangements it is asked for, does the refutation ledger record them, does the
parse describe the board honestly -- not to answer "what is level 7's rule".

THE STANDING RULE, and it is the one that matters: no number produced through this file
is a result. Anything reported as a score comes from a full run starting at level 1, and
`assert_not_scorable()` below makes a jumped session refuse to be treated as one.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def make_at_level(game: str, level: int, seed: int = 0):
    """An environment already sitting on `level` (1-indexed), plus its first frame.

    Returns (env, frame, jumped) where `jumped` is False when level == 1, so a caller
    that did not actually skip anything is not marked unscorable for no reason.
    """
    import arc_agi

    env = arc_agi.Arcade().make(game, seed=seed, include_frame_data=True)
    frame = env.reset()
    if level <= 1:
        return env, frame, False

    engine = getattr(env, "_game", None)
    if engine is None or not hasattr(engine, "set_level"):
        raise RuntimeError(
            "this engine exposes no set_level; run from level 1 instead of pretending"
        )
    engine.set_level(level - 1)
    # The board only materialises on the next step, exactly as it does after a real level
    # transition, so the caller is handed a frame that is actually the new level.
    #
    # That step must be FREE. `action_space[0]` is action 5, submit, which costs a cell of
    # the move bar -- the jumped session then opened with a bar already eaten into, the
    # full-bar colour was never learned, and `clock()` reported unconfirmed for the whole
    # level. That is an artifact of the jump and not something a real run sees, and an
    # artifact that makes the debug session lie about the agent's budget is worse than no
    # debug session. Undo costs nothing and is inert on an untouched board.
    free = next((a for a in env.action_space if int(a.value) == 7), env.action_space[-1])
    frame = env.step(free) or frame
    return env, frame, True


def assert_not_scorable(frame, jumped: bool) -> None:
    """Refuse to let a jumped session be mistaken for a result.

    The check is not a formality. `levels_completed` is what every result artifact in
    this repo reports, and after a jump it is zero -- so a jumped run that somehow
    cleared level 7 would still read as 0/8. This states that plainly and loudly rather
    than letting a number leave the file quietly.
    """
    if not jumped:
        return
    completed = getattr(frame, "levels_completed", None)
    print("=" * 70)
    print("DEBUG SESSION -- NOT A RESULT")
    print(f"  levels_completed reads {completed}: the scorecard credits nothing for the")
    print("  levels that were skipped, so nothing here can be reported as a score.")
    print("  Scores come from a full run starting at level 1.")
    print("=" * 70)
    if completed:
        raise AssertionError(
            f"a jumped session reported levels_completed={completed}; it must be 0. "
            "Something is crediting skipped levels and no number from this run is safe."
        )


def main() -> int:
    import argparse


    from evals.arc.codeact_agent import Env
    from evals.arc.frames import parse

    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="sb26")
    ap.add_argument("--level", type=int, default=7)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    raw, frame, jumped = make_at_level(args.game, args.level, args.seed)
    assert_not_scorable(frame, jumped)

    env = Env(raw, frame, turn_action_cap=4000)
    layout = parse(env.grid())
    if not layout:
        print("board did not parse")
        return 1

    pads = sorted(layout["pads"], key=lambda p: (p["cy"], p["cx"]))
    print(f"\nlevel {args.level} of {args.game}")
    print(f"  pads   {len(pads)}: {[(int(p['cx']), int(p['cy'])) for p in pads]}")
    print(f"  tray   {sorted(int(t['colour']) for t in layout['tray'])}")
    print(f"  clues  {[int(c['colour']) for c in layout['clues']]}")
    print(f"  shape  {layout['clue_structure']}")
    print(f"  frames {[(int(f['colour']), int(f['x0']), int(f['y0']), int(f['x1']), int(f['y1'])) for f in layout['frames']]}")
    print(f"  clock  {env.clock()}")
    print(f"  seated {env.seated()}")

    # How many candidate assignments does this board actually admit? The number the
    # agent is searching against, stated rather than assumed.
    from collections import Counter
    from math import factorial

    stock = Counter(int(t["colour"]) for t in layout["tray"])
    total = factorial(len(pads))
    for n in stock.values():
        total //= factorial(n)
    print(f"\n  {len(pads)} pads over tray {dict(stock)} = {total} distinct assignments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
