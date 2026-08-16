"""Is a reset free, and does it cost you the levels you already cleared?

The prompt used to answer both questions wrongly in four words -- `reset() -> restart
from level 1` -- and an agent that believes that will never call the only free move the
game has. It will instead spend actions walking a board back by hand, and every one of
those actions is squared against its score.

Both halves of the claim are checkable without touching the network, because both live
in the vendored `arc_agi` package this harness plays through:

  1. IS IT FREE?  The scorecard has two counters, `inc_action_count` and
     `inc_reset_count`, and `update_scorecard` decides between them by the id of the
     action taken. Action id 0 is RESET, and it routes to the reset counter. RHAE divides
     by the action count, so a reset never enters the number.

  2. DOES IT COST LEVELS?  Every death in this harness calls the same `_env.reset()` the
     agent's `reset()` calls. If reset restarted the game, a run that died mid-game would
     reappear on level 1. Recorded traces say otherwise, and this check reads them: it
     looks for a trace where deaths happened and asserts the level count never fell.

Run: python -m evals.arc.reset_check
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.trace_integrity import last_run_rows  # noqa: E402

RESULTS = Path("eval/arc-results")


def _fail(msg: str) -> str:
    return f"FAIL  {msg}"


def _ok(msg: str) -> str:
    return f"ok    {msg}"


def check_reset_is_not_an_action() -> tuple[bool, list[str]]:
    """RESET must route to the reset counter, never the action counter."""
    out: list[str] = []
    try:
        mod = importlib.import_module("arc_agi.scorecard")
    except Exception as exc:  # pragma: no cover - environment without the package
        return False, [_fail(f"cannot import arc_agi.scorecard: {exc}")]

    src = inspect.getsource(mod)
    i = src.find("def update_scorecard(\n        self, guid: str, data: FrameDataRaw")
    if i < 0:
        i = src.find("def update_scorecard")
    body = src[i : i + 1200]

    # The RESET branch: action id 0 -> new_play (a genuinely new play) or reset().
    reset_branch = re.search(r"action_input\.id\.value in \[0\]", body)
    if not reset_branch:
        return False, [_fail("update_scorecard no longer dispatches on action id 0")]
    # Cut the branch at the NEXT dispatch, or a window that runs on will read the
    # move-action branch below it and conclude the opposite of the truth.
    rest = body[reset_branch.end():]
    nxt = re.search(r"action_input\.id\.value in \[", rest)
    tail = rest[: nxt.start()] if nxt else rest[:260]
    if "inc_action_count" in tail or "take_action" in tail:
        return False, [_fail("RESET now increments the ACTION count -- reset is no longer free")]
    if "self.reset(" not in tail and "new_play" not in tail:
        return False, [_fail("RESET branch no longer routes to the reset counter")]
    out.append(_ok("RESET routes to the reset counter, not the action counter"))

    reset_fn = src[src.find("def reset(self, game_id") :][:300]
    if "inc_reset_count" not in reset_fn:
        return False, [_fail("scorecard.reset no longer calls inc_reset_count")]
    out.append(_ok("scorecard.reset increments resets only"))

    # And the branch that DOES spend an action must exclude 0, so the two are disjoint.
    act = re.search(r"action_input\.id\.value in \[([0-9, ]+)\]", rest)
    if not act:
        return False, [_fail("no move-action branch found to compare against")]
    ids = [p.strip() for p in act.group(1).split(",")]
    if "0" in ids:
        return False, [_fail("action id 0 also counted as an action")]
    out.append(_ok(f"the action counter covers ids {','.join(ids)} -- RESET is outside it"))
    return True, out


def check_harness_reset_spends_nothing() -> tuple[bool, list[str]]:
    """Our own Env.reset must not touch the action counter either."""
    src = Path("evals/arc/codeact_agent.py").read_text(encoding="utf-8")
    i = src.find("    def reset(self):")
    if i < 0:
        return False, [_fail("Env.reset not found")]
    body = src[i : src.find("\n    def ", i + 10)]
    if "self.spent" in body:
        return False, [_fail("Env.reset touches self.spent; a reset must cost no action")]
    out = [_ok("Env.reset does not increment self.spent")]

    # The two caches that describe the OLD board must be dropped with it.
    for name in ("_bar_colour", "_bar_row"):
        if name not in body:
            return False, [_fail(f"Env.reset leaves {name} cached from the pre-reset board")]
    out.append(_ok("Env.reset drops the bar cache, so no frozen reading survives it"))
    return True, out


def check_prompt_tells_the_truth() -> tuple[bool, list[str]]:
    """The docstring the agent reads must not say reset restarts the game."""
    src = Path("evals/arc/codeact_agent.py").read_text(encoding="utf-8")
    i = src.find("    reset()")
    if i < 0:
        return False, [_fail("reset() is not documented in the API block")]
    entry = src[i : i + 1100]
    if re.search(r"restart from level 1", entry, re.I):
        return False, [_fail("the prompt still tells the agent reset restarts from level 1")]
    out = [_ok("the prompt no longer claims reset restarts the game")]
    if not re.search(r"COSTS NO ACTION|costs no action", entry):
        return False, [_fail("the prompt does not tell the agent a reset is free")]
    out.append(_ok("the prompt states a reset costs no action"))
    if not re.search(r"DOES NOT REFUND|does not refund", entry):
        return False, [_fail("the prompt does not warn that reset refunds nothing")]
    out.append(_ok("the prompt warns that spent actions are not refunded"))
    return True, out


def check_traces_kept_their_levels() -> tuple[bool, list[str]]:
    """In a recorded run, deaths (which reset) must never lower the level count."""
    traces = sorted(RESULTS.glob("trace-*.jsonl"))
    if not traces:
        return True, ["skip  no traces on disk to read"]

    examined = 0
    for path in traces:
        # Only the most recent run in the file. A tag collision puts two runs in one
        # trace, and reading both makes the second run's fresh start look like the first
        # run's levels being destroyed -- which is precisely the false alarm this check
        # raised against cd82-ev3 ("level count fell 3 -> 0. A reset really does restart
        # the game, and the prompt fix is wrong"). cd82-ev3 holds 240 rows against a
        # 120-turn cap.
        lo, hi = last_run_rows(path)
        levels: list[int] = []
        index = -1
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    if isinstance(row, dict) and isinstance(row.get("turn"), int):
                        index += 1
                        if not (lo <= index < hi):
                            continue
                    if isinstance(row, dict) and isinstance(row.get("levels"), int):
                        levels.append(row["levels"])
        except (OSError, json.JSONDecodeError):
            continue
        if len(levels) < 2 or max(levels) == 0:
            continue
        examined += 1
        for a, b in zip(levels, levels[1:]):
            if b < a:
                return False, [
                    _fail(
                        f"{path.name}: level count fell {a} -> {b}. A reset really does "
                        "restart the game, and the prompt fix is wrong."
                    )
                ]

    if not examined:
        # Traces exist and none of them reached level 1: either every run on disk is
        # trivial, or the last_run_rows filter above is discarding everything. The second
        # is a live risk because that filter was added today, and a check that examines
        # nothing while reporting success is the exact failure mode that made eight
        # checks vacuous this session. Verified: blinding the filter turns this green
        # unless it is refused here.
        return False, [
            _fail(
                f"{len(traces)} trace(s) on disk but NONE were examined. This check "
                "cannot pass without evidence -- suspect the trace-integrity filter."
            )
        ]
    return True, [
        _ok(
            f"{examined} recorded run(s) never lost a cleared level, across every death "
            "-- and a death is a reset"
        )
    ]


def main() -> int:
    checks = (
        ("RESET is free on the scorecard", check_reset_is_not_an_action),
        ("Env.reset spends nothing", check_harness_reset_spends_nothing),
        ("the prompt tells the truth", check_prompt_tells_the_truth),
        ("cleared levels survive a reset", check_traces_kept_their_levels),
    )
    bad = 0
    for title, fn in checks:
        good, lines = fn()
        print(f"\n== {title}")
        for line in lines:
            print("  " + line)
        if not good:
            bad += 1

    print()
    if bad:
        print(f"{bad} CHECK(S) FAILED")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
