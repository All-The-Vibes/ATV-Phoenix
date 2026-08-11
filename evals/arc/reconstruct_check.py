"""Prove the click-log reader survives the noise a real agent makes.

The gate is only as good as the orders it banks. If the reader mangles a log, the gate
rejects correct rules and the agent is pushed back towards fitting noise -- so this
checks the reader against the specific ways a real log is messier than pick/drop pairs.
Costs nothing: no game, no model, no network.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.rule_gate import (  # noqa: E402
    placements_from_clicks,
    rounds_from_clicks,
)

LAYOUT = {
    "pads": [
        {"x0": 20, "x1": 24, "y0": 20, "y1": 24, "cx": 22, "cy": 22},
        {"x0": 26, "x1": 30, "y0": 20, "y1": 24, "cx": 28, "cy": 22},
        {"x0": 38, "x1": 42, "y0": 20, "y1": 24, "cx": 40, "cy": 22},
    ],
    "tray": [
        {"colour": 12, "x0": 4, "x1": 7, "y0": 48, "y1": 51, "cx": 5, "cy": 50},
        {"colour": 15, "x0": 8, "x1": 11, "y0": 48, "y1": 51, "cx": 9, "cy": 50},
        {"colour": 6, "x0": 12, "x1": 15, "y0": 48, "y1": 51, "cx": 13, "cy": 50},
    ],
}

TRUTH = [(12, (22, 22)), (15, (28, 22)), (6, (40, 22))]


def case(name, log, expect, layout=None):
    got = placements_from_clicks(log, layout or LAYOUT)
    ok = got == expect
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        expected {expect}")
        print(f"        got      {got}")
    return ok


clean = [
    (5, 50, 12), (22, 22, 0),
    (9, 50, 15), (28, 22, 0),
    (13, 50, 6), (40, 22, 0),
]

# A probe on empty background between placements: the old index pairing read this as a
# pick-up and shifted every placement after it.
probed = [
    (5, 50, 12), (22, 22, 0),
    (33, 8, 0),
    (9, 50, 15), (28, 22, 0),
    (60, 60, 0), (1, 1, 0),
    (13, 50, 6), (40, 22, 0),
]

# The agent looks at the board before touching anything.
front_loaded = [(0, 0, 0), (63, 63, 0), (31, 5, 0)] + clean

# A click that lands on nothing while holding: not a pad, so not a drop.
missed_drop = [
    (5, 50, 12), (55, 5, 0), (22, 22, 0),
    (9, 50, 15), (28, 22, 0),
    (13, 50, 6), (40, 22, 0),
]

# Truncated: the level cleared but the log only shows two of three pieces. Recording
# this would bank an order no correct rule reproduces, so the reader must decline.
partial = clean[:4]

# A colour that is not in the tray at all -- decoration, not a piece.
foreign = [(7, 7, 3)] + clean

# THE BUG THAT WAS LIVE: the agent placed all three pieces, got it wrong, and placed
# them again in the order that won. The reader must bank the SECOND round. Reading the
# first one records a losing order as the solution, and then no correct rule can pass.
wrong_first = [
    (5, 50, 12), (40, 22, 0),
    (9, 50, 15), (22, 22, 0),
    (13, 50, 6), (28, 22, 0),
]
retried = wrong_first + clean

# Three attempts, and the winner is still the last one.
thrice = wrong_first + wrong_first + clean

# A round that was abandoned half-way is not a candidate at all.
abandoned_then_won = [(5, 50, 12), (22, 22, 0), (9, 50, 15)] + clean

# THE OTHER LIVE BUG: from level 4 the game draws some pieces hollow, so clicking the
# centre of the c6 square reads the colour of the hole (4) instead of the piece. The
# piece must be identified by where it sits, not by the pixel under the cursor.
hollow = [
    (5, 50, 12), (22, 22, 0),
    (9, 50, 15), (28, 22, 0),
    (13, 50, 4), (40, 22, 0),
]

# DUPLICATE COLOURS: from level 5 the tray ships two of some colours (level 5 has two
# c8s and two c9s). A reader that treats a repeated colour as the start of a new attempt
# chops the winning round in half and banks nothing.
DUP_LAYOUT = {
    "pads": LAYOUT["pads"] + [
        {"x0": 44, "x1": 48, "y0": 20, "y1": 24, "cx": 46, "cy": 22},
    ],
    "tray": [
        {"colour": 9, "x0": 4, "x1": 7, "y0": 48, "y1": 51, "cx": 5, "cy": 50},
        {"colour": 9, "x0": 8, "x1": 11, "y0": 48, "y1": 51, "cx": 9, "cy": 50},
        {"colour": 6, "x0": 12, "x1": 15, "y0": 48, "y1": 51, "cx": 13, "cy": 50},
        {"colour": 12, "x0": 16, "x1": 19, "y0": 48, "y1": 51, "cx": 17, "cy": 50},
    ],
}
DUP_TRUTH = [(9, (22, 22)), (9, (28, 22)), (6, (40, 22)), (12, (46, 22))]
dup_log = [
    (5, 50, 9), (22, 22, 0),
    (9, 50, 9), (28, 22, 0),
    (13, 50, 6), (40, 22, 0),
    (17, 50, 12), (46, 22, 0),
]
# And a failed attempt before it, still with duplicates in play.
dup_retried = [
    (5, 50, 9), (46, 22, 0),
    (9, 50, 9), (40, 22, 0),
    (13, 50, 6), (28, 22, 0),
    (17, 50, 12), (22, 22, 0),
] + dup_log

results = [
    case("clean log", clean, TRUTH),
    case("probe clicks between placements", probed, TRUTH),
    case("looks around before playing", front_loaded, TRUTH),
    case("missed drop, then hits the pad", missed_drop, TRUTH),
    case("incomplete log is refused, not guessed", partial, []),
    case("non-tray colour ignored", foreign, TRUTH),
    case("failed attempt then the winning one", retried, TRUTH),
    case("two failed attempts then the winner", thrice, TRUTH),
    case("abandoned half-round then the winner", abandoned_then_won, TRUTH),
    case("hollow piece reads its hole's colour", hollow, TRUTH),
    case("duplicate colours in the tray", dup_log, DUP_TRUTH, DUP_LAYOUT),
    case("duplicates, failed attempt then winner", dup_retried, DUP_TRUTH, DUP_LAYOUT),
]

# Testing several candidates in one turn is the intended way to use the action budget, so
# every attempt in the log has to come back, not just the last. Refuting only the final
# one would throw away three quarters of the evidence a batched turn produces.
batched = wrong_first + clean + wrong_first
rounds = rounds_from_clicks(batched, LAYOUT)
print()
print(f"three attempts in one turn -> {len(rounds)} recovered")
all_three = len(rounds) == 3 and rounds[1] == TRUTH
print(f"{'PASS' if all_three else 'FAIL'}  every attempt in a batched turn is recovered")
results.append(all_three)

last_only = placements_from_clicks(batched, LAYOUT)
print(f"{'PASS' if last_only == rounds[-1] else 'FAIL'}  the last attempt is still "
      f"identified for banking")
results.append(last_only == rounds[-1])

# The bug this was written to kill: show the old reader actually breaks on `probed`.
old = []
for i in range(0, len(probed) - 1, 2):
    (_, _, colour), (px, py, _) = probed[i], probed[i + 1]
    if colour:
        old.append((colour, (px, py)))
print()
print(f"old index-pairing reader on the probed log -> {old}")
print(f"                                    truth -> {TRUTH}")
regression_real = old != TRUTH
print(f"{'PASS' if regression_real else 'FAIL'}  the bug was real (old reader mangles it)")

# And the second bug: a first-round reader banks the attempt that lost.
first_round_reader = placements_from_clicks(wrong_first, LAYOUT)
print()
print(f"a first-round reader on the retried log -> {first_round_reader}")
print(f"                                 truth -> {TRUTH}")
retry_bug_real = first_round_reader != TRUTH
print(f"{'PASS' if retry_bug_real else 'FAIL'}  the retry bug was real (losing order != winner)")

ok = all(results) and regression_real and retry_bug_real
print()
print("ALL GREEN" if ok else "SOMETHING IS RED")
sys.exit(0 if ok else 1)
