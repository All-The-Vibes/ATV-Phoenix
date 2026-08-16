"""The guidance was gated on the agent having already taken the advice.

Both interventions -- the death message and the stall message -- used to read

    if died and env.level_notes:
    elif stalled >= 6 and env.level_notes:

so an agent holding an empty notebook was told nothing at all. An empty notebook is
not the signature of an agent that needs no help. It is the signature of the ones
that are stuck:

  bp35-b   45 turns, 20 deaths, 0 notes, 0 mechanics, 0 levels  -- never advised
  ka59-c   cleared level 1 at turn 6, then 90 turns and 2,732 actions with 0 notes
  m0r0-m1  last clear at turn 3 of 93; 98% of its actions came after it
  lf52-m1  89% of its actions came after its last clear

Corpus-wide: 54,999 of 88,764 actions ever spent -- 62% -- came AFTER the run's last
level clear. The single largest pool of waste in the project, and the harness's two
tools for interrupting it were switched off for exactly the runs generating it.

Free. No API calls, no game, no spend.
"""
import ast
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import evals.arc.codeact_agent as mod  # noqa: E402


def _guidance_conditions():
    """The `if`/`elif` tests that decide whether the agent is advised at all."""
    src = inspect.getsource(mod.play)
    tree = ast.parse(src.lstrip())
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if test == "died" or test.startswith("died "):
            found["death"] = test
        elif "stalled >= 6" in test:
            found["stall"] = test
    return found


def check_guidance_is_not_gated_on_notes():
    """Neither message may require the notebook it exists to ask the agent to fill."""
    cond = _guidance_conditions()
    missing = [k for k in ("death", "stall") if k not in cond]
    if missing:
        return False, f"could not find the {', '.join(missing)} branch in play()"
    bad = [f"{k}: `{v}`" for k, v in cond.items() if "level_notes" in v]
    if bad:
        return False, ("guidance still gated on already having notes -- " + "; ".join(bad))
    return True, f"death fires on `{cond['death']}`, stall on `{cond['stall']}`"


def check_empty_notebook_gets_its_own_advice():
    """With no notes, 'retract the wrong note' is not actionable. Say something usable."""
    src = inspect.getsource(mod.play)
    problems = []
    if "YOU ARE HOLDING NO NOTES" not in src:
        problems.append("no branch addresses the empty-notebook case")
    # The advice must name the free tool that fixes it.
    empty_advice = src.split("YOU ARE HOLDING NO NOTES")
    for chunk in empty_advice[1:]:
        window = chunk[:900]
        if "note(text)" not in window:
            problems.append("the empty-notebook advice never names note(text)")
            break
    if problems:
        return False, "; ".join(problems)
    return True, "the empty-notebook case is addressed and names note(text) as the fix"


def check_advice_still_warns_against_buying_information():
    """The measured negative result must survive this edit.

    Telling a stalled agent to run more experiments took a run from 1,026 to 4,212
    actions and 13.67% to 0.53%. Any rewrite of the stall message that loses this
    warning re-creates the most expensive mistake in the project's history.
    """
    src = inspect.getsource(mod.play)
    if "more probing is what turned a" not in src:
        return False, "the stall message no longer warns against buying information with actions"
    if "FREE tools" not in src and "free" not in src:
        return False, "the stall message no longer points at the free tools"
    return True, "the 1,026 -> 4,212 warning and the free-tools pointer both survive"


CHECKS = [
    ("guidance is not gated on already having notes", check_guidance_is_not_gated_on_notes),
    ("an empty notebook gets usable advice", check_empty_notebook_gets_its_own_advice),
    ("the exploration warning survives", check_advice_still_warns_against_buying_information),
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
    print("stall guidance: ALL PASS" if not bad else f"stall guidance: {bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
