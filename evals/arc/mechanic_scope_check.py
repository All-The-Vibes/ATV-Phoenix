"""A coordinate is not a rule of the game.

`mechanic()` is the one memory no level change ever clears. That is its value and it
is the whole risk: a fact about where something sits on THIS board, written as a rule
of the game, is a lie that survives every board after it and cannot be retracted by
the level boundary that disproved it.

Measured on ka59: level 1 fell in 40 actions. The run then recorded

    "For an upper-left destination: enter the central vertical shaft near x=25,
     rise to y=26, cross left into ..."
    "For a lower-left destination, align near y=44 and cross left directly ..."

as rules of the game, and spent 2,732 further actions on level 2 steering by level 1's
geometry without clearing it.

The cause was the prompt, not the agent. `note()` was described in one line;
`mechanic()` got twenty-four lines of advocacy and a sentence saying that on every game
without a rule gate, mechanic() is "the thing you write the answer into". Twelve runs
obeyed exactly -- ar25, bp35, cn04, g50t, ka59, ls20, sp80 -- calling mechanic() up to
111 times and note() zero times, and they are the games that are stuck.

Free. No API calls, no game, no spend.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evals.arc.codeact_agent import SYSTEM, _looks_board_specific  # noqa: E402

# Verbatim from trace-ka59-c.jsonl. These were stored as rules of the game.
BOARD_SPECIFIC = [
    "For an upper-left destination: enter the central vertical shaft near x=25, rise to "
    "y=26, cross left into the upper-left bay.",
    "For a lower-left destination, align near y=44 and cross left directly through the "
    "lower central opening.",
    "The exit sits at (31, 16) on this board.",
    "The hazard occupies row 44 and must be approached from the left.",
    "Park the vertical piece at column 7 before submitting.",
    "The tray refills at 12,3 after each drop.",
]

# Real rules of the game. None of these may be flagged, or the mark becomes noise and
# the agent learns to ignore it -- which is how a warning stops being a warning.
GENUINE_RULES = [
    "action 3 moves you north",
    "obstacles reflect particles",
    "Directional actions move the selected piece by 3 cells.",
    "Click a loose piece to select it; a black centre confirms selection.",
    "Movable pieces and yellow destinations are shape-matched.",
    "A move costs one cell of the move bar; a submit costs one more.",
    "Pieces cross the central divider at their current row.",
    "The bar drains one cell per piece dropped and one per submit.",
]


def check_board_facts_are_flagged():
    missed = [t for t in BOARD_SPECIFIC if not _looks_board_specific(t)]
    if missed:
        return False, f"{len(missed)} board fact(s) not flagged, e.g. {missed[0][:70]!r}"
    return True, f"all {len(BOARD_SPECIFIC)} board-specific rules flagged, including ka59's real two"


def check_genuine_rules_are_not_flagged():
    flagged = [t for t in GENUINE_RULES if _looks_board_specific(t)]
    if flagged:
        return False, f"{len(flagged)} genuine rule(s) wrongly flagged, e.g. {flagged[0][:70]!r}"
    return True, f"none of {len(GENUINE_RULES)} genuine rules flagged; a step size is not a coordinate"


def check_prompt_states_the_test():
    """The prompt must say a coordinate is not a mechanic, and must not tell the agent
    that mechanic() is where answers go."""
    problems = []
    if "A COORDINATE IS NEVER A MECHANIC" not in SYSTEM:
        problems.append("the prompt never says a coordinate is not a mechanic")
    if "the thing you write the answer into is mechanic()" in SYSTEM:
        problems.append(
            "the prompt still tells the agent mechanic() is where the answer goes, "
            "which is what produced twelve runs with zero notes"
        )
    if "This is the DEFAULT" not in SYSTEM:
        problems.append("note() is not stated as the default home for what you learn")
    if problems:
        return False, "; ".join(problems)
    return True, "the prompt states the redraw test and names note() as the default"


def check_warning_reaches_the_caller():
    """A flagged write must say so in its return value, not only in the display."""
    import evals.arc.codeact_agent as mod
    import inspect

    src = inspect.getsource(mod.Env.mechanic)
    if "_COORD" not in src or "warning" not in src:
        return False, "mechanic() does not warn its caller when the text names a coordinate"
    if "unmechanic(" not in src:
        return False, "the warning does not tell the agent how to undo the write"
    return True, "mechanic() returns a warning naming unmechanic() as the way back"


CHECKS = [
    ("board facts are flagged", check_board_facts_are_flagged),
    ("genuine rules are left alone", check_genuine_rules_are_not_flagged),
    ("the prompt states the redraw test", check_prompt_states_the_test),
    ("the warning reaches the caller", check_warning_reaches_the_caller),
]


def main():
    bad = 0
    for title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {title}\n       {detail}")
        bad += not ok
    print("-" * 74)
    print("mechanic scope: ALL PASS" if not bad else f"mechanic scope: {bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
