"""Is the move-bar reported truthfully? Plays the real game.

This exists because the harness spent every run telling the agent something false about
the one budget that kills it. `mechanics.json` said the row-53 bar was a TIMER draining
"as ticks pass" and instructed the agent to budget its turn against the clock. Measured:

    click a tray piece (pick up) ..... 0 cells
    click a pad (DROP a piece) ....... 1 cell
    press(5) submit .................. 1 cell
    press(7) undo .................... 0 cells
    click empty space ................ 0 cells

It is a mutation counter, not a clock, and the difference is seven deaths and 1,367
actions on level 7 of a measured fair run: the agent planned six attempts a turn against a
bar that afforded seven per LIFE, and had no way to see the meter.

Every check here fails on the pre-fix code -- `clock` did not exist, `budget` did not
exist, and the mechanics text asserted the timer reading.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from evals.arc.frames import budget, parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MECHANICS = ROOT / "eval" / "arc-results" / "mechanics.json"


def main() -> int:
    ok = True

    # ── the note must no longer teach the clock reading ──────────────────────────────
    text = json.loads(MECHANICS.read_text(encoding="utf-8")).get("sb26", "")
    lies = [phrase for phrase in ("as ticks pass", "BAR IS A TIMER", "is a countdown and")
            if phrase in text]
    good = not lies
    print(f"{'PASS' if good else 'FAIL'}  mechanics.json no longer calls the bar a timer "
          f"({lies})")
    ok = ok and good

    truths = ["MOVE BUDGET", "clock()", "DROPPED"]
    said = [t for t in truths if t in text]
    good = len(said) == len(truths)
    print(f"{'PASS' if good else 'FAIL'}  mechanics.json states the measured cost model "
          f"({said})")
    ok = ok and good

    # ── clock() must exist in the agent's namespace ──────────────────────────────────
    import ast

    from evals.arc import codeact_agent as agent

    src = Path(agent.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    exposed = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "click" in keys and "press" in keys and "clock" in keys:
            exposed = True
    print(f"{'PASS' if exposed else 'FAIL'}  clock() is in the agent's REPL namespace")
    ok = ok and exposed

    has_died = any(isinstance(n, ast.ClassDef) and n.name == "Died"
                   for n in ast.walk(tree))
    print(f"{'PASS' if has_died else 'FAIL'}  a death raises into the agent's code (Died)")
    ok = ok and has_died

    # ── and the reading must match the live game, action by action ───────────────────
    import arc_agi

    env = arc_agi.Arcade().make("sb26", include_frame_data=True)
    frame = env.reset()
    by_value = {int(a.value): a for a in env.action_space}

    def grid():
        arr = np.array(frame.frame, dtype=int)
        return arr[0] if arr.ndim == 3 else arr

    full = budget(grid())
    good = full["confirmed"] and full["left"] == full["total"] and full["total"] > 1
    print(f"{'PASS' if good else 'FAIL'}  a fresh board reads as a full bar "
          f"({full['left']}/{full['total']} on row {full['row']})")
    ok = ok and good
    colour = full["full_colour"]

    def spend(label, value, data=None):
        nonlocal frame
        before = budget(grid(), colour)["left"]
        frame = env.step(by_value[value], data) if data else env.step(by_value[value])
        after = budget(grid(), colour)["left"]
        return label, before - after

    layout = parse(grid())
    tray, pads = layout["tray"], layout["pads"]

    costs = [
        spend("pick up a tray piece", 6, {"x": tray[0]["cx"], "y": tray[0]["cy"]}),
        spend("DROP it on a pad", 6, {"x": pads[0]["cx"], "y": pads[0]["cy"]}),
        spend("undo", 7),
        spend("click empty space", 6, {"x": 1, "y": 1}),
        spend("submit", 5),
    ]
    expected = {"pick up a tray piece": 0, "DROP it on a pad": 1, "undo": 0,
                "click empty space": 0, "submit": 1}
    for label, cost in costs:
        want = expected[label]
        good = cost == want
        print(f"{'PASS' if good else 'FAIL'}  {label:<22} costs {cost} cell(s), "
              f"expected {want}")
        ok = ok and good

    # The reading has to stay faithful once the bar is partly eaten, which is the case a
    # single-frame parse cannot resolve on its own.
    partial = budget(grid(), colour)
    good = (partial["confirmed"] and partial["used"] == 2
            and partial["left"] + partial["used"] == partial["total"])
    print(f"{'PASS' if good else 'FAIL'}  a partly-eaten bar still reads correctly "
          f"(left={partial['left']} used={partial['used']} total={partial['total']})")
    ok = ok and good

    blind = budget(grid())
    good = not blind["confirmed"]
    print(f"{'PASS' if good else 'FAIL'}  without the full-bar colour it declines to "
          f"guess a direction (confirmed={blind['confirmed']})")
    ok = ok and good

    # More than one row can pass the full-width two-colour shape test. On a measured run
    # the stale frame served at a level boundary made row 0 -- a band of ordinary board
    # colours -- read as a full bar that did not exist. The meter is the row that actually
    # MOVES when a piece is dropped, so that is what is asserted, rather than a property
    # of the drawing that happens to correlate with it.
    picked = budget(grid(), colour)["row"]
    before = grid().copy()
    frame = env.step(by_value[6], {"x": tray[1]["cx"], "y": tray[1]["cy"]})
    frame = env.step(by_value[6], {"x": pads[1]["cx"], "y": pads[1]["cy"]})
    moved = [y for y in range(before.shape[0])
             if not np.array_equal(before[y], grid()[y])]
    good = picked in moved
    print(f"{'PASS' if good else 'FAIL'}  the row it calls the bar is the row a DROP moves "
          f"(picked {picked}, drop moved {moved})")
    ok = ok and good

    decoys = [y for y in moved if y != picked]
    good = picked is not None
    print(f"{'PASS' if good else 'FAIL'}  a bar row was identified at all "
          f"(other rows the drop touched: {decoys})")
    ok = ok and good

    # ── the differential-test mechanic ───────────────────────────────────────────────
    #
    # The lever that bounds a searched level. A hypothesis costs pads+1 cells to build
    # from scratch, so on eight pads one life funds seven. But if a PLACED piece can be
    # lifted and moved, the second hypothesis costs only the pads that changed -- two or
    # three, typically -- which is roughly three times more hypotheses per life. The
    # harness never told the agent this was possible.
    # Establish the precondition rather than assuming it. By this point the checks above
    # have placed, undone and submitted, so neither the tray nor any given pad is in a
    # known state -- an earlier draft "lifted" from an empty pad, which is a no-op that
    # costs 0 and would have passed the assertion while measuring nothing. A fresh
    # environment makes the precondition explicit.
    env2 = arc_agi.Arcade().make("sb26", include_frame_data=True)
    frame2 = env2.reset()

    def grid2():
        arr = np.array(frame2.frame, dtype=int)
        return arr[0] if arr.ndim == 3 else arr

    colour2 = budget(grid2())["full_colour"]

    def cost_of(label, x, y):
        nonlocal frame2
        before_bar = budget(grid2(), colour2)["left"]
        before_img = grid2().copy()
        frame2 = env2.step(by_value[6], {"x": int(x), "y": int(y)})
        return (label,
                before_bar - budget(grid2(), colour2)["left"],
                not np.array_equal(before_img, grid2()))

    fresh = parse(grid2())
    seat_pad, target = fresh["pads"][0], fresh["pads"][2]
    cost_of("pick", fresh["tray"][0]["cx"], fresh["tray"][0]["cy"])
    cost_of("seat", seat_pad["cx"], seat_pad["cy"])

    label, lift, moved_board = cost_of("lift a piece already ON a pad",
                                       seat_pad["cx"], seat_pad["cy"])
    good = lift == 0 and moved_board
    print(f"{'PASS' if good else 'FAIL'}  {label:<32} costs {lift} cell(s) and changes "
          f"the board (moved={moved_board})")
    ok = ok and good

    label, redrop, _ = cost_of("re-drop it on another pad", target["cx"], target["cy"])
    good = redrop == 1
    print(f"{'PASS' if good else 'FAIL'}  {label:<32} costs {redrop} cell(s), expected 1")
    ok = ok and good

    n_pads = len(fresh["pads"])
    good = lift + redrop < n_pads + 1
    print(f"{'PASS' if good else 'FAIL'}  moving one piece ({lift + redrop}) is cheaper "
          f"than rebuilding ({n_pads + 1})")
    ok = ok and good

    text = json.loads(MECHANICS.read_text(encoding="utf-8")).get("sb26", "")
    good = "ALREADY ON A PAD" in text
    print(f"{'PASS' if good else 'FAIL'}  mechanics.json tells the agent a placed piece "
          f"can be moved")
    ok = ok and good

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
