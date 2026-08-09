"""Is the run fair? Offline, zero API spend.

The harness is allowed to tell the agent how the GAME works -- that submit is action 5,
that a click picks up and a click drops, that the row-53 bar is a timer -- because those
are invisible on screen and would otherwise cost actions to discover. It is NOT allowed to
tell the agent which colour belongs on which pad. That is the puzzle.

The line was crossed once already and it was not noticed for eleven runs: `mechanics.json`
carried a worked solution for two levels, including a literal pad-to-colour table, and it
is injected into every single turn. Levels 1 and 2 cost exactly 9 and 16 actions in every
run because the agent was replaying an answer, not solving a board.

This file is the standing check that it stays that way.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
MECHANICS = ROOT / "eval" / "arc-results" / "mechanics.json"

# A pad-to-colour statement in any of the shapes this repo has actually written one in:
#   (22,22)=12        the table style
#   (12, (22, 22))    the placement-list style
ASSIGNMENT = re.compile(
    r"\(\s*\d{1,2}\s*,\s*\d{1,2}\s*\)\s*=\s*\d{1,2}"
    r"|\(\s*\d{1,2}\s*,\s*\(\s*\d{1,2}\s*,\s*\d{1,2}\s*\)\s*\)"
)

# Phrases that announce a solved board rather than a mechanic.
SOLVED = [
    "the winning assignment",
    "solved. verified offline",
    "the answer is above",
    "do not permute",
    "solves in 9 actions",
]


def main() -> int:
    ok = True

    text = MECHANICS.read_text(encoding="utf-8") if MECHANICS.exists() else ""
    if not text:
        print("FAIL  mechanics.json is missing")
        return 1

    hits = ASSIGNMENT.findall(text)
    good = not hits
    print(f"{'PASS' if good else 'FAIL'}  mechanics.json states no pad-to-colour "
          f"assignment ({len(hits)} found)")
    if hits:
        for h in hits[:6]:
            print(f"        {h}")
    ok = ok and good

    low = text.lower()
    said = [s for s in SOLVED if s in low]
    good = not said
    print(f"{'PASS' if good else 'FAIL'}  mechanics.json announces no solved level "
          f"({len(said)} found)")
    for s in said:
        print(f"        {s!r}")
    ok = ok and good

    # The regex has to be able to catch the thing it exists to catch.
    was_real = bool(ASSIGNMENT.findall("(22,22)=12  (28,22)=15")) and bool(
        ASSIGNMENT.findall("[(12, (22, 22)), (15, (28, 22))]"))
    print(f"{'PASS' if was_real else 'FAIL'}  the check can detect a real leak "
          f"(both historical shapes)")
    ok = ok and was_real

    # The solver must not be reachable from the agent's namespace. `frame_plan` derives
    # the answer from hand-written sb26 clue grammars, so exposing it under any name
    # would measure the harness rather than the agent.
    #
    # Checked through the AST rather than by searching the text: the source carries a
    # comment explaining why `order()` was REMOVED, and a text search matched that
    # comment and reported a leak that was not there. Comments do not survive parsing.
    import ast

    from evals.arc import codeact_agent as agent  # noqa: E402

    src = Path(agent.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    exposed: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "click" not in keys or "press" not in keys:
            continue  # not the agent's REPL namespace
        for value in node.values:
            text_value = ast.unparse(value)
            for banned in ("frame_plan", "traverse", "_expand", "_reference"):
                if banned in text_value:
                    exposed.append(f"{banned} via {text_value[:60]}")
    good = not exposed
    print(f"{'PASS' if good else 'FAIL'}  the solver is not in the agent's namespace "
          f"({exposed})")
    ok = ok and good

    # And the check must be able to see a leak if one is reintroduced.
    probe = ast.parse('ns = {"press": a, "click": b, "order": lambda: frame_plan(g)}')
    caught = False
    for node in ast.walk(probe):
        if isinstance(node, ast.Dict):
            for value in node.values:
                if "frame_plan" in ast.unparse(value):
                    caught = True
    print(f"{'PASS' if caught else 'FAIL'}  the namespace check can see a real leak")
    ok = ok and caught

    # layout() may describe the board's SHAPE. It must not hand over a finished mapping.
    from evals.arc.frames import parse  # noqa: E402

    import inspect
    keys = re.search(r"return \{\"frames\".*?\}", inspect.getsource(parse), re.S)
    shape = keys.group(0) if keys else ""
    forbidden = [k for k in ("assignment", "answer", "solution", "order\"") if k in shape]
    good = not forbidden
    print(f"{'PASS' if good else 'FAIL'}  layout() returns shape, not a mapping "
          f"({forbidden})")
    ok = ok and good

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
