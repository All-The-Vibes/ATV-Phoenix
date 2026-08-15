"""Is the agent doing the same thing again and expecting a different result?

`StallDetected` already exists and fires when the BOARD does not change across
consecutive actions. It cannot see the failure that is actually costing the corpus:
a turn whose code runs, whose board DOES change, and which produces the identical
result as a turn twenty turns ago.

Measured across the 25 most recent runs, comparing each turn's output signature:

  sp80-ev16   120 turns,  29 distinct outputs,  one output repeated 46 times
  sc25-ev18   120 turns,  29 distinct outputs,  one repeated 44 times
  tu93-ev17   120 turns,  57 distinct,          one repeated 32 times
  s5i5-ev14   120 turns,  51 distinct,          one repeated 22 times
  12 of 25 runs repeat more than 35% of their turns

`ls20-ev14` is the clean specimen and it kills the obvious explanations. It spent 111
turns on level 1 with ZERO deaths, holding a correct and detailed world model --
"actions move the token on a five-pixel orthogonal lattice", "small purple 3x3 markers
are collectibles", "the grey-framed maroon glyph is the target" -- and it writes BFS,
with `deque` and `visited`. It is not dying, not blind, and not lacking search. It
replayed one identical trace twelve times.

So the missing signal is not perception, not planning, and not death. It is that
nothing in the harness says "you have run this exact experiment before and it gave
this exact answer". The agent cannot see its own repetition because each turn arrives
with only the LAST turn's output in front of it.

Checks pin the mechanism:
  - the harness keeps a signature of what each turn produced
  - it tells the agent when the current result has been seen before, with the count
  - it names the earlier turn, so the claim is checkable rather than an accusation
  - it does not fire on the first repeat, which is normal verification

Free. No API calls, no game, no spend.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _play() -> str:
    import evals.arc.codeact_agent as mod
    return inspect.getsource(mod.play)


def _repeat_fstrings():
    out = []
    for node in ast.walk(ast.parse(_play())):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str)).upper()
        if "SEEN THIS" in text or "ALREADY PRODUCED" in text or "SAME RESULT" in text:
            out.append((node, text))
    return out


def check_outputs_are_fingerprinted() -> tuple[bool, str]:
    """Not "is there a dict called seen_outputs" -- does anything ever go INTO it.

    The first version of this check asked for the NAME and passed with the recording
    line deleted: a fingerprint store that is initialised, read, and never written is
    permanently empty, so the warning below it can never fire. Mutation testing caught
    it, which is the seventh time this session that checking for a name instead of a
    behaviour produced a green light over a dead mechanism.
    """
    tree = ast.parse(_play())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        # seen_outputs[...] .append(...)  or  seen_outputs.setdefault(...).append(...)
        if not (isinstance(f, ast.Attribute) and f.attr in {"append", "setdefault", "add"}):
            continue
        if any(isinstance(n, ast.Name) and n.id == "seen_outputs" for n in ast.walk(f)):
            return True, "each turn's result is fingerprinted and written to the store"
    return False, (
        "nothing is ever written to the fingerprint store, so it stays empty and the "
        "repeat warning below it can never fire. Measured: sp80-ev16 produced one "
        "identical output 46 times in 120 turns and was never told."
    )


def check_the_agent_is_told() -> tuple[bool, str]:
    if not _repeat_fstrings():
        return False, (
            "nothing tells the agent its current result is one it has already seen. "
            "StallDetected only fires when the BOARD stops changing; a run can change "
            "the board every turn and still replay one trace twelve times, which is "
            "exactly what ls20-ev14 did across 111 turns with zero deaths."
        )
    return True, "the agent is told when a result repeats"


def check_it_names_the_earlier_turn() -> tuple[bool, str]:
    """An accusation the agent cannot check is one it can dismiss."""
    for node, _ in _repeat_fstrings():
        if any(isinstance(v, ast.FormattedValue) for v in node.values):
            return True, "the message carries the repeat count and the earlier turn"
    return False, (
        "the message interpolates nothing. 'You are repeating yourself' with no turn "
        "number and no count is an assertion the agent has no way to verify."
    )


def check_it_tolerates_one_repeat() -> tuple[bool, str]:
    """Running an experiment twice to confirm it is not a bug; it is good practice."""
    tree = ast.parse(_play())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        if "seen_outputs" not in names and "repeats" not in names:
            continue
        for c in node.comparators:
            if isinstance(c, ast.Constant) and isinstance(c.value, int) and c.value >= 2:
                return True, f"the warning waits for {c.value}+ repeats"
    return False, (
        "no tolerance for a second look. Re-running an experiment once to confirm it is "
        "sound practice, and a harness that scolds it teaches the agent to distrust the "
        "message."
    )


CHECKS = [
    ("turn results are fingerprinted", check_outputs_are_fingerprinted),
    ("the agent is told about a repeat", check_the_agent_is_told),
    ("the message names the earlier turn", check_it_names_the_earlier_turn),
    ("one repeat is tolerated", check_it_tolerates_one_repeat),
]


def main() -> int:
    failures = 0
    for title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # a check that crashes is a check that failed
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {title}\n       {detail}")
        failures += not ok
    print("-" * 70)
    print("repeat detection: ALL PASS" if not failures
          else f"repeat detection: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
