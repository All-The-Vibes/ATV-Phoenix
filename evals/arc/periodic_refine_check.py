"""Does the agent ever step back and tidy what it believes?

Prime Agent's Continual Harness auto-refines every 25 assistant turns
(`_assistantTurnsSinceAutoRefine >= settings.turnInterval`, default 25, confirmed in
`agent-session.ts`), with a 20-minute cooldown, on root sessions only. The refiner
reads the last 80,000 characters of trajectory plus the current harness state and
emits CRUD edits over four kinds of state: prompt notes, memories, skills, sub-agents.

This harness has all the CRUD primitives -- note, mechanic, retract, unmechanic,
learn -- and no moment that asks the agent to USE them on itself. Everything fires on
an event: a death, a stall, a level clear. Nothing fires on "you have been going a
while, is what you believe still true?"

Measured on the last 15 runs: 75 such moments passed with no consolidation. Runs are
120-240 turns; at Prime Agent's interval that is 4-9 refine points per run, every one
of them skipped.

The gap that matters is not tidiness. Beliefs here are ADDITIVE within a level -- the
agent writes notes as it learns and only ever removes one when something contradicts
it hard enough to notice. A theory that was true on turn 10 and quietly stopped being
true by turn 60 is still steering at turn 120, because nothing ever asked.

Checks pin the mechanism, not the wording:
  - a periodic consolidation exists, on an interval rather than an event
  - it fires on a schedule and not every turn
  - it shows the agent what it currently believes, so the ask is answerable
  - it does not fire on a run too short to have accumulated anything

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


def _refine_fstrings():
    """f-strings that read like the periodic self-review ask."""
    out = []
    for node in ast.walk(ast.parse(_play())):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str)).upper()
        if "STILL TRUE" in text or "REVIEW WHAT YOU BELIEVE" in text:
            out.append((node, text))
    return out


def check_a_periodic_review_exists() -> tuple[bool, str]:
    src = _play()
    if "refine_at" not in src:
        return False, (
            "nothing asks the agent to review its own beliefs on an interval. Every "
            "existing prompt fires on an EVENT -- a death, a stall, a clear -- so a "
            "theory that quietly stopped being true is never revisited. Measured: 75 "
            "review points passed unused across the last 15 runs."
        )
    if not _refine_fstrings():
        return False, "a refine interval is computed but no message is built from it"
    return True, "a periodic belief review exists"


def check_it_is_on_an_interval() -> tuple[bool, str]:
    """On a schedule, not every turn: a review every turn is not a review."""
    for node in ast.walk(ast.parse(_play())):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "turn" in names:
                return True, "the review is gated on a turn interval"
    return False, (
        "the review is not on a turn interval. Firing every turn makes it noise the "
        "agent learns to skip, which is how the stall message ended up ignored for 150 "
        "consecutive turns on cd82-ev3."
    )


def check_it_shows_the_beliefs() -> tuple[bool, str]:
    """Asking 'is it still true?' without showing what 'it' is asks for a guess."""
    for node, _ in _refine_fstrings():
        if any(isinstance(v, ast.FormattedValue) for v in node.values):
            return True, "the review interpolates the agent's current beliefs"
    return False, (
        "the review carries no interpolated state. Prime Agent's refiner reads the "
        "last 80k characters of trajectory plus the full harness state; an ask with "
        "neither is a request to reconstruct from memory."
    )


def check_it_waits_for_a_long_enough_run() -> tuple[bool, str]:
    """A run 20 turns old has not had time to accumulate a stale belief."""
    src = _play()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.dump(node.test)
        if "refine_at" not in test:
            continue
        for cmp_node in ast.walk(node.test):
            if isinstance(cmp_node, ast.Compare):
                for c in cmp_node.comparators:
                    if isinstance(c, ast.Constant) and isinstance(c.value, int) \
                            and c.value >= 15:
                        return True, (f"the review waits until turn {c.value} before "
                                      f"firing")
    return False, (
        "no minimum-age gate. A review on turn 5 reviews nothing and trains the agent "
        "to ignore the message before it ever carries information."
    )


CHECKS = [
    ("a periodic belief review exists", check_a_periodic_review_exists),
    ("it fires on an interval, not every turn", check_it_is_on_an_interval),
    ("it shows the agent what it believes", check_it_shows_the_beliefs),
    ("it waits for a long enough run", check_it_waits_for_a_long_enough_run),
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
    print("periodic refine: ALL PASS" if not failures
          else f"periodic refine: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
