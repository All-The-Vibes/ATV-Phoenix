"""Is the agent told which level is worth fighting for?

RHAE weights a level by its INDEX: `weighted += index * score` over a weight sum of
`1+2+...+N`. On an eight-level game, level 8 carries 8/36 of the score and level 1
carries 1/36. Reward is capped at 1.15, and the penalty is unbounded toward zero. So
the game score is dominated by how the LATE levels went, and one bad late level costs
more than several good early ones can repay.

Measured across nine revisits this session, that is exactly what separated the runs
that improved from the runs that did not -- per-level ratio of human actions to agent
actions, in level order:

  lp85 r16  WIN   [3.4, 1.9, 1.24, 0.22, 3.42, 0.13, 1.73, 2.04]
  tr87 r16  WIN   [1.38, 1.76, 1.33, 1.61, 0.2, 0.84]
  sb26 r15  WIN   [2.0, 1.12, 0.86, 1.19, 1.72, 1.15, 1.76, 0.03]
  cd82 r16  LOSS  [1.08, 0.5, 0.47, 0.09, 0.23, 0.11]
  dc22 r17  LOSS  [0.55, 0.83, 0.19]
  cn04 r17  LOSS  [1.53, 0.15]

The losses are not slower everywhere. cd82 cleared level 1 faster than the human and
then spent roughly ten times the human budget on levels 4, 5 and 6 -- the three
heaviest. Its game score is 12.69% almost entirely because of that.

The harness already tells the agent its pace on the CURRENT level. It has never told
it that levels are not worth the same, nor how the levels it already cleared are
scoring. That is a signal the harness holds and the agent cannot derive, which is the
same class of defect as every other fix in this file: not a lie, but a silence.

Free. No API calls, no game, no spend.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _pace_fstrings():
    """f-strings in `play` that build the per-level pace message."""
    import evals.arc.codeact_agent as mod

    tree = ast.parse(inspect.getsource(mod.play))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
        if "THIS LEVEL" in text or "human took" in text:
            out.append((node, text))
    return out


def check_level_weight_is_shown() -> tuple[bool, str]:
    """The agent must know a late level is worth more than an early one."""
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod.play)
    if "level_weight" not in src:
        return False, (
            "the agent is never told what this level is WORTH. RHAE weights a level by "
            "its index -- level 8 of 8 carries 8/36 of the game and level 1 carries "
            "1/36 -- so it cannot know that the level in front of it is the one that "
            "decides the score."
        )
    for _, text in _pace_fstrings():
        if "worth" in text.lower() and "%" in text:
            return True, "the pace message states what this level is worth"
    return False, "level weight is computed but never reaches the agent"


def check_worst_cleared_level_is_reported() -> tuple[bool, str]:
    """A game score is dragged down by its worst level; name it.

    The penalty is unbounded while reward caps at 1.15, so the cheapest available
    improvement on a re-run is almost always the level that went worst, not the one
    that went best. The harness knows which that was and never said.
    """
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod.play)
    if "worst" not in src.lower():
        return False, (
            "the agent is never shown which of its cleared levels is scoring worst. "
            "cd82 spent ~10x the human budget on its three heaviest levels and was "
            "told only that its current pace was poor."
        )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ).lower()
        if "worst" in text and any(isinstance(v, ast.FormattedValue) for v in node.values):
            return True, "the worst cleared level is named with its numbers"
    return False, "a worst level is computed but never interpolated into a message"


def check_it_does_not_fire_before_there_is_evidence() -> tuple[bool, str]:
    """With no level cleared there is no worst level, and no honest claim to make."""
    import evals.arc.codeact_agent as mod

    tree = ast.parse(inspect.getsource(mod.play))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(node.test) if isinstance(n, ast.Attribute)}
        if "level_actions" in names | attrs or "best" in attrs:
            for inner in ast.walk(node):
                if isinstance(inner, ast.JoinedStr):
                    text = "".join(
                        v.value for v in inner.values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    ).lower()
                    if "worst" in text:
                        return True, "the report is gated on a level having been cleared"
    return False, (
        "nothing gates the worst-level report on there being a cleared level to "
        "report on; on level 1 it would describe an empty list."
    )


CHECKS = [
    ("this level's weight is shown", check_level_weight_is_shown),
    ("the worst cleared level is named", check_worst_cleared_level_is_reported),
    ("no claim before there is evidence", check_it_does_not_fire_before_there_is_evidence),
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
    print("level economics: ALL PASS" if not failures
          else f"level economics: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
