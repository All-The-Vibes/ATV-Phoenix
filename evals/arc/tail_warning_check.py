"""The run that is already lost, told so while it can still change.

Measured across 150 traces on disk. The discriminator is "still on level 0 after
spending K times the human's level-1 action budget":

    K   tripped   of those, ended >3x human   precision   fast runs wrongly tripped
    1       118                          76         64%                           0
    2        90                          74         82%                           0
    3        69                          69        100%                           0
    4        56                          56        100%                           0

At K=3 the separation is total on the evidence available: sixty-nine runs crossed it
and sixty-nine ended in the slow tail, while not one run that finished at or under the
human baseline ever tripped it. An agent three times over budget with nothing cleared
has never recovered.

That matters because the corpus score is a variance problem more than a capability
one. The same agent clears cd82's level 1 in 16 actions and in 328; sb26's in 9 and in
139. Sampling more runs converts that spread into score under max-of-runs, but it does
nothing about the tail itself. This is the other half: name the bad draw while the run
is still going.

What it does NOT do is reset or abort. A reset buys back the BOARD and never the
BUDGET -- the actions are spent and RHAE has already charged them -- so a harness that
silently restarted here would burn the same actions again with the same approach. The
finding is that the APPROACH is wrong, not that the board is unlucky, so the agent is
told exactly that, with the number and the evidence, and left to decide.

Stated as evidence rather than as prophecy: 69 of 69 is what the record shows, not a
law, and the message says so.

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


def check_the_threshold_exists() -> tuple[bool, str]:
    """The harness must compute the over-budget-and-nothing-cleared condition."""
    src = _play()
    if "tail_warned" not in src:
        return False, (
            "nothing detects a run that is already in the bad tail. Measured on 150 "
            "traces: an agent 3x over the human level-1 budget with no level cleared "
            "ended slow in 69 of 69 cases, and the harness said nothing."
        )
    return True, "the harness detects the over-budget, nothing-cleared condition"


def check_it_fires_only_before_the_first_clear() -> tuple[bool, str]:
    """After a level falls the evidence no longer applies; the claim would be false."""
    src = _play()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.dump(node.test)
        if "tail_warned" not in test:
            continue
        # The condition must involve having cleared nothing.
        if "best" in test or "level_actions" in test:
            return True, "the warning is gated on no level having been cleared yet"
    return False, (
        "the warning is not gated on the run having cleared nothing. After a clear the "
        "69-of-69 evidence does not apply and the claim would be false."
    )


def check_it_fires_once() -> tuple[bool, str]:
    """Repeating it every turn turns evidence into nagging."""
    src = _play()
    tree = ast.parse(src)
    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "tail_warned"
                       for t in n.targets)]
    if len(assigns) < 2:
        return False, (
            "the warning has no latch, so it would repeat every turn for the rest of "
            "the run. A message the agent sees forty times is a message it stops "
            "reading."
        )
    return True, "the warning latches and fires once"


def check_it_states_the_evidence() -> tuple[bool, str]:
    """A prediction without its basis is a guess the agent cannot weigh."""
    src = _play()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
        if "69 of 69" in text or "69 of the 69" in text:
            if any(isinstance(v, ast.FormattedValue) for v in node.values):
                return True, "the warning carries its evidence and this run's numbers"
    return False, (
        "the warning does not state what it is based on. 69 of 69 is a record, not a "
        "law, and an agent told 'you will fail' without the basis cannot weigh it."
    )


CHECKS = [
    ("the tail condition is detected", check_the_threshold_exists),
    ("it fires only before the first clear", check_it_fires_only_before_the_first_clear),
    ("it fires once, not every turn", check_it_fires_once),
    ("it states the evidence", check_it_states_the_evidence),
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
    print("tail warning: ALL PASS" if not failures
          else f"tail warning: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
