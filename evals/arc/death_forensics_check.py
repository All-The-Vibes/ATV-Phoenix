"""Gap 9: a death that records only a count teaches nothing.

Twenty-five deaths on `bp35-r3` produced three learned mechanics, and all three
were movement primitives -- action 3 moves left, 4 moves right, 7 coasts. Not one
described the hazard, because the harness never told the agent what the hazard
did. The `Died` message reported a death COUNT and a LIFE LENGTH, and the one
board that held the evidence -- the terminal frame -- was handed to
`self._env.reset()` and destroyed unread.

The evidence was always in reach. `_step` holds the last-alive frame at the line
that computes `changed` and overwrites it on the next line, so the two boards
either side of the killing action both exist for exactly one statement.

This pins the recovery four ways: the capture is present and ordered before the
reset, a synthetic death names the action that caused it and the cells that moved,
the report describes the KILLING STEP rather than the whole life, and a malformed
board costs nothing.

Free. No API calls, no game, no spend.
"""
import ast
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from evals.arc.codeact_agent import _death_forensics  # noqa: E402
except ImportError:
    # Absent is a FAILING state, not a crashing one. Letting the import kill the
    # module would abort every check at once and prove only that one name is
    # missing -- the same vacuous gate this suite exists to avoid. Each check
    # must be seen failing on its own terms before it can be trusted green.
    def _death_forensics(prev_grid, term_grid, recent_actions):  # noqa: D103
        return ""


def _blank(n=8):
    return [[0] * n for _ in range(n)]


def check_source_shape():
    """The capture must exist and must run BEFORE the board is rebuilt."""
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod)
    tree = ast.parse(src)

    # 1. _step must stash the outgoing frame before it is replaced.
    step = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_step"), None)
    if step is None:
        return False, "_step is gone; this check is aimed at the wrong function"

    stash_line = replace_line = None
    for node in ast.walk(step):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Attribute):
                continue
            if tgt.attr == "_prev_frame" and stash_line is None:
                stash_line = node.lineno
            if tgt.attr == "_frame" and replace_line is None:
                replace_line = node.lineno
    if stash_line is None:
        return False, "_step never stashes the last-alive frame as self._prev_frame"
    if replace_line is not None and stash_line > replace_line:
        return False, (f"_step stashes at line {stash_line} but replaces self._frame at "
                       f"{replace_line}; the stash would hold the NEW frame")

    # 2. The death branch must call the forensics before it resets the env.
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_death_forensics"]
    if not calls:
        return False, "nothing calls _death_forensics; the terminal frame is still discarded"
    resets = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "reset"]
    first_call = min(c.lineno for c in calls)
    later_resets = [r for r in resets if r > first_call]
    if not later_resets:
        return False, (f"_death_forensics is called at line {first_call} but no reset() "
                       "follows it; the read is not happening on the terminal board")
    return True, (f"frame stashed at line {stash_line}, forensics read at {first_call}, "
                  f"board rebuilt at {min(later_resets)}")


def check_names_the_killing_action():
    """The agent is told which action it died on, and what led there."""
    prev, term = _blank(), _blank()
    term[3][4] = 9
    out = _death_forensics(prev, term, [3, 4, 4, 3, 7, 4])
    if not out:
        return False, "the forensics returned nothing for a well-formed death"
    if "4" not in out:
        return False, f"the killing action is not named:\n{out}"
    if "3, 4, 4, 3, 7" not in out.replace(",", ", ").replace("  ", " "):
        joined = ",".join(str(a) for a in [3, 4, 4, 3, 7, 4])
        if joined not in out.replace(" ", ""):
            return False, f"the run-up to the death is not shown:\n{out}"
    return True, "the report names the killing action and the actions before it"


def check_names_what_moved():
    """The cells that changed in the killing step are reported, with where."""
    prev, term = _blank(), _blank()
    # A hazard (colour 9) lands on the player (colour 4) at x=5, y=2.
    prev[2][5] = 4
    term[2][5] = 9
    prev[2][6] = 9
    term[2][6] = 0
    out = _death_forensics(prev, term, [4])
    if not out:
        return False, "the forensics returned nothing for a well-formed death"
    if "4->9" not in out.replace(" ", "") and "4 -> 9" not in out:
        return False, f"the colour that replaced the player is not reported:\n{out}"
    if "5" not in out or "2" not in out:
        return False, f"the location of the change is not reported:\n{out}"
    return True, "the report names the colour transition and where it happened"


def check_describes_only_the_killing_step():
    """A board that changed everywhere earlier must not be summarised here."""
    prev, term = _blank(), _blank()
    prev[0][0] = 7
    term[0][0] = 7  # unchanged: must NOT be counted
    prev[1][1] = 4
    term[1][1] = 9  # the only change
    out = _death_forensics(prev, term, [4])
    digits = [int(t) for t in out.replace(":", " ").split() if t.isdigit()]
    if 1 not in digits:
        return False, f"the changed-cell count of 1 is not reported:\n{out}"
    if "7" in out:
        return False, f"an unchanged cell leaked into the report:\n{out}"
    return True, "only the cells that changed in the killing step are reported"


def check_identical_boards_are_honest():
    """If nothing visibly changed, say so rather than inventing a cause."""
    out = _death_forensics(_blank(), _blank(), [4])
    if not out:
        return False, "an unchanged board produced no report at all"
    low = out.lower()
    if not any(w in low for w in ("no visible", "nothing visible", "did not change",
                                 "no cells changed", "unchanged")):
        return False, f"an unchanged board was not reported honestly:\n{out}"
    return True, "a death with no visible board change is reported as exactly that"


def check_never_raises():
    """Forensics must never end a two-hour run."""
    bad = [
        (None, _blank(), [4]),
        (_blank(), None, [4]),
        ([[0, 1], [2]], _blank(), [4]),          # ragged
        (_blank(4), _blank(8), [4]),             # mismatched shapes
        (_blank(), _blank(), []),                # no actions recorded
        ("not a grid", _blank(), [4]),
    ]
    for i, (a, b, acts) in enumerate(bad):
        try:
            out = _death_forensics(a, b, acts)
        except Exception as exc:
            return False, f"case {i} raised {type(exc).__name__}: {exc}"
        if not isinstance(out, str):
            return False, f"case {i} returned {type(out).__name__}, not str"
    return True, f"all {len(bad)} malformed inputs returned a string instead of raising"


CHECKS = [
    ("capture is present and precedes the rebuild", check_source_shape),
    ("the killing action is named", check_names_the_killing_action),
    ("what moved onto the player is named", check_names_what_moved),
    ("only the killing step is described", check_describes_only_the_killing_step),
    ("an invisible cause is reported honestly", check_identical_boards_are_honest),
    ("malformed boards cost nothing", check_never_raises),
]


def main():
    failures = 0
    for title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # a check that crashes is a check that failed
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {title}\n       {detail}")
        failures += not ok
    print("-" * 70)
    print("death forensics: ALL PASS" if not failures
          else f"death forensics: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
