"""Sanity check: does RuleGate tell a rule from a lookup table? Offline, zero API spend.

Two candidates are put through the gate against real sb26 boards:

* the frame-traversal rule from `frames.py`, which derives placements from the board and
  clears levels 1-6,
* a lookup table of the exact literal shape the agent actually wrote on level 2.

The gate is only worth wiring in if it accepts the first and refuses the second with a
counterexample. If it accepts both, it is decoration.
"""
from __future__ import annotations

import sys
from pathlib import Path

import random

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import arc_agi  # noqa: E402

from evals.arc.codeact_agent import Env, LevelCleared  # noqa: E402
from evals.arc.frames import parse, plan  # noqa: E402
from evals.arc.rule_gate import RuleGate  # noqa: E402


def collect(max_levels=4):
    """Clear levels with the known-good rule, recording each board and its order."""
    arc = arc_agi.Arcade()
    raw = arc.make("sb26", include_frame_data=True)
    env = Env(raw, raw.reset(), inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)

    gate = RuleGate()
    while env.levels() < max_levels:
        layout = parse(env.grid())
        steps = plan(env.grid())
        if not layout or not steps:
            break
        level = env.levels() + 1
        pool = list(layout["tray"])
        # Keep the grid with the layout so a candidate rule has the same raw board the
        # agent would see. Without it, a "rule" could only read pre-digested fields and
        # the test would not be measuring derivation from the board at all.
        layout = {**layout, "grid": env.grid().copy()}
        try:
            for colour, pad in steps:
                src = next((t for t in pool if t["colour"] == colour), None)
                if src is None:
                    return gate
                pool.remove(src)
                env.click(src["cx"], src["cy"])
                env.click(*pad)
            env.press(5)
        except LevelCleared:
            gate.remember(level, layout, steps)
            try:
                env.press(7)
            except LevelCleared:
                pass
            continue
        break
    return gate


def real_rule(layout):
    """Derives the order from the board it is handed. This is what a theory looks like."""
    return plan(layout["grid"])


def shuffled_rule(layout):
    """The same correct assignment, walked in a different order.

    The board accepts this -- measured, nine shuffles of a winning assignment cleared
    across levels 3, 4 and 5 -- so the gate has to accept it too. A gate that refuses it
    is telling the agent a correct rule is wrong.
    """
    steps = list(plan(layout["grid"]))
    random.Random(0).shuffle(steps)
    return steps


def lookup_table(layout):
    """The literal shape the agent wrote on level 2, verbatim in structure.

    It ignores its argument entirely, which is precisely the defect: it encodes one
    board's answer and cannot respond to a different board.
    """
    return [
        (12, (22, 22)), (15, (28, 22)), (6, (40, 22)),
        (8, (22, 36)), (9, (28, 36)), (14, (34, 36)), (11, (40, 36)),
    ]


def main() -> int:
    gate = collect(4)
    levels = [b.level for b in gate.solved]
    print(f"collected solved boards: {levels}\n")
    if len(levels) < 2:
        print("need at least 2 solved boards to test generalisation")
        return 1

    print("--- candidate A: the real frame-traversal rule ---")
    verdict_a = gate.propose(real_rule)
    print(f"  ok={verdict_a['ok']}  {verdict_a['reason'][:160]}\n")

    print("--- candidate A': the same assignment, walked in a different order ---")
    verdict_s = gate.propose(shuffled_rule)
    print(f"  ok={verdict_s['ok']}  {verdict_s['reason'][:160]}\n")

    print("--- candidate B: the lookup table the agent actually wrote ---")
    verdict_b = gate.propose(lookup_table)
    print(f"  ok={verdict_b['ok']}  {verdict_b['reason'][:200]}")
    if verdict_b["failed"]:
        first = verdict_b["failed"][0]
        print(f"  counterexample: level {first['level']} -> {first['why']}")

    print()
    works = verdict_a["ok"] and verdict_s["ok"] and not verdict_b["ok"]
    if not verdict_s["ok"]:
        print("  the gate refused a CORRECT rule for walking the pads in another order")
    print("SANITY CHECK:", "PASS - the gate separates a rule from a table, and judges "
          "the assignment rather than the path"
          if works else "FAIL - the gate does not discriminate")
    return 0 if works else 1


if __name__ == "__main__":
    raise SystemExit(main())
