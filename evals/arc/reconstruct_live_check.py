"""Does the click-log reader survive the REAL game? Offline, zero API spend.

`reconstruct_check.py` tests the reader against logs I wrote by hand, and
`rule_gate_check.py` tests the gate against orders handed to it directly by the planner.
Neither one exercises the seam between them: clicks going through the actual Env, and the
order being read back out of `env.click_log`. That seam is where the gate was silently
banking nothing -- a live run cleared levels 1-4 and the gate still reported only level 1.

So this plays real sb26 levels with the known-good planner, then asks the reader to
recover the order from the click log alone and compares it to the order actually played.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import arc_agi  # noqa: E402

from evals.arc.codeact_agent import Env, LevelCleared, _parsed  # noqa: E402
from evals.arc.frames import parse, plan  # noqa: E402
from evals.arc.rule_gate import placements_from_clicks  # noqa: E402


def main(max_levels=4) -> int:
    arc = arc_agi.Arcade()
    raw = arc.make("sb26", include_frame_data=True)
    env = Env(raw, raw.reset(), inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)

    ok = True
    while env.levels() < max_levels:
        layout = parse(env.grid())
        steps = plan(env.grid())
        if not layout or not steps:
            break
        level = env.levels() + 1
        board = {**layout, "grid": env.grid().copy()}
        pool = list(layout["tray"])
        env.click_log = []
        board_mid = None

        try:
            for i, (colour, pad) in enumerate(steps):
                src = next((t for t in pool if t["colour"] == colour), None)
                if src is None:
                    print(f"level {level}: planner named a colour not in the tray")
                    return 1
                pool.remove(src)
                env.click(src["cx"], src["cy"])
                env.click(*pad)
            env.press(5)
        except LevelCleared:
            log = list(env.click_log)
            # Exactly what the agent loop does: bank from the board Env captured for
            # this level, not from anything the test kept on the side.
            agent_board = _parsed(env.level_grid)
            got = placements_from_clicks(log, agent_board) if agent_board else []
            want = [(int(c), (int(p[0]), int(p[1]))) for c, p in steps]
            norm = [(int(c), (int(p[0]), int(p[1]))) for c, p in got] if got else []
            good = norm == want
            ok = ok and good
            print(f"{'PASS' if good else 'FAIL'}  level {level}: "
                  f"{len(log)} clicks -> {len(norm)} placements")
            if not good:
                print(f"        played      {want}")
                print(f"        reconstructed {norm}")
                tray_cols = [int(t['colour']) for t in board['tray']]
                print(f"        tray colours {tray_cols}")
                if agent_board is None:
                    print("        Env captured no level board at all")
                else:
                    print(f"        Env board tray={len(agent_board['tray'])} "
                          f"pads={len(agent_board['pads'])}")

            # The board right after the clear still shows the level just solved, with an
            # empty tray. Banking THAT is what silently threw four levels away, so pin it.
            stale = _parsed(env.grid())
            stale_n = len(stale["tray"]) if stale else 0
            if stale_n:
                print(f"        NOTE post-clear board still has {stale_n} tray pieces; "
                      "this level does not exercise the stale-board trap")
            else:
                print("        (confirmed: post-clear board has an empty tray -- "
                      "Env's captured board is required)")

            env.click_log = []
            env.forget_level_board()
            try:
                env.press(7)
            except LevelCleared:
                pass
            continue
        print(f"level {level}: submit did not clear")
        return 1

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
