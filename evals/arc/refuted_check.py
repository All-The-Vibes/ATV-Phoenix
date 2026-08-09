"""Does the refuted-attempt ledger turn wasted attempts into usable evidence?

Replayed against the twelve orders a real run actually played on level 5. Every one of
them passed the held-out test and every one was refused by the board, so the solved levels
were exhausted as evidence and the run stalled for thirteen turns. The ledger's job is to
say what those failures had in common. Offline, zero API spend.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.rule_gate import RuleGate  # noqa: E402

TOP = [(19, 22), (25, 22), (31, 22), (37, 22), (43, 22)]
CHILD = [(25, 36), (31, 36), (37, 36)]

# The twelve distinct assignments a real run played on level 5, read verbatim out of
# eval/arc-results/trace-rulegate6.jsonl, turns 8-20. Every one reproduced levels 1-4 and
# was accepted by propose(); every one was refused by the board.
ATTEMPTS = [
    [(6, (19, 22)), (14, (25, 22)), (8, (31, 22)), (8, (25, 36)), (9, (31, 36)),
     (9, (37, 36)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (14, (25, 22)), (8, (31, 22)), (9, (25, 36)), (8, (31, 36)),
     (9, (37, 36)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (14, (25, 22)), (8, (31, 22)), (9, (25, 36)), (9, (31, 36)),
     (8, (37, 36)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (14, (25, 22)), (9, (25, 36)), (14, (31, 36)), (9, (37, 36)),
     (8, (31, 22)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (14, (25, 22)), (8, (31, 22)), (9, (25, 36)), (14, (31, 36)),
     (9, (37, 36)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (8, (25, 22)), (9, (25, 36)), (14, (31, 36)), (9, (37, 36)),
     (8, (31, 22)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (8, (25, 22)), (8, (31, 22)), (14, (25, 36)), (9, (31, 36)),
     (9, (37, 36)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (9, (25, 36)), (15, (31, 36)), (9, (37, 36)), (8, (25, 22)),
     (8, (31, 22)), (14, (37, 22)), (11, (43, 22))],
    [(6, (19, 22)), (14, (25, 22)), (8, (25, 36)), (9, (31, 36)), (9, (37, 36)),
     (8, (31, 22)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (11, (25, 22)), (15, (31, 22)), (9, (25, 36)), (14, (31, 36)),
     (9, (37, 36)), (8, (37, 22)), (8, (43, 22))],
    [(6, (19, 22)), (8, (25, 22)), (8, (31, 22)), (9, (25, 36)), (14, (31, 36)),
     (9, (37, 36)), (11, (37, 22)), (15, (43, 22))],
    [(6, (19, 22)), (8, (25, 22)), (8, (31, 22)), (9, (25, 36)), (9, (31, 36)),
     (14, (37, 36)), (11, (37, 22)), (15, (43, 22))],
]

# What actually clears level 5, measured. Not one of the twelve went near it.
TRUTH = [(6, (19, 22)), (9, (25, 22)), (9, (31, 22)), (11, (37, 22)), (15, (43, 22)),
         (14, (25, 36)), (8, (31, 36)), (8, (37, 36))]


def as_order(order):
    return list(order)


def main() -> int:
    gate = RuleGate()
    ok = True

    for order in ATTEMPTS:
        gate.refute(as_order(order))
    saved = len(ATTEMPTS) - len(gate.refuted)
    print(f"{len(ATTEMPTS)} played sequences collapse to {len(gate.refuted)} distinct "
          f"assignments")
    # The collapse is the point: those were attempts the board had already refused, paid
    # for again at ~17 actions each because they were reached by a different route.
    print(f"{'PASS' if saved > 0 else 'FAIL'}  reordered repeats are caught "
          f"({saved} attempts, ~{saved * 17} actions, were wasted for real)")
    ok = ok and saved > 0

    # A replayed assignment must cost nothing. The real run played one twice.
    repeat = gate.refute(as_order(ATTEMPTS[0]))
    dup = gate.already_refuted(as_order(ATTEMPTS[0]))
    print(f"{'PASS' if not repeat and dup else 'FAIL'}  a repeat is recognised, not re-run")
    ok = ok and (not repeat) and dup

    # The board scores a mapping, not a path: the same assignment dropped in a different
    # sequence is the same answer, and re-testing it would waste 17 actions.
    reordered = list(reversed(as_order(ATTEMPTS[0])))
    same = gate.already_refuted(reordered)
    print(f"{'PASS' if same else 'FAIL'}  the same assignment, reordered, is recognised")
    ok = ok and same

    fresh = gate.already_refuted(as_order(TRUTH))
    print(f"{'PASS' if not fresh else 'FAIL'}  the untried winning assignment is NOT refused")
    ok = ok and not fresh

    shown = gate.shared_constraints()
    print(f"\nwhat the agent is shown ({len(shown)}):")
    for s in shown:
        print(f"  {s}")

    # The constraints must contradict the winning assignment, or they are just trivia.
    truth_map = {p: c for c, p in TRUTH}
    contradicts = []
    for s in shown:
        if s.startswith("colour "):
            colour = int(s.split()[1])
            tried = {p for p, c in truth_map.items() if c == colour}
            never = eval(s.split("never once on ")[1])  # noqa: S307
            if tried.intersection(never):
                contradicts.append(s)
        else:
            pad = eval(s.split("pad ")[1].split(" was handed")[0])  # noqa: S307
            colour = int(s.rsplit(" colour ", 1)[1].split()[0])
            if truth_map.get(pad) != colour:
                contradicts.append(s)
    print(f"\n{len(contradicts)} of them are FALSE in the assignment that actually wins:")
    for s in contradicts:
        print(f"  {s}")
    good = bool(contradicts)
    print(f"\n{'PASS' if good else 'FAIL'}  the ledger points away from the fixation")
    ok = ok and good

    gate.clear_refuted()
    cleared = not gate.refuted and not gate.already_refuted(as_order(ATTEMPTS[0]))
    print(f"{'PASS' if cleared else 'FAIL'}  a new level starts with a clean ledger")
    ok = ok and cleared

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
