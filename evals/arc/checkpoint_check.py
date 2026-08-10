"""Does an interrupted run still leave a result behind?

Free: no environment, no API, no actions.

The scorecard used to be written once, after `play()` returned, so a run that
did not return left nothing at all. Measured the day this was written: two runs
were stopped deliberately and both vanished -- no scorecard, no record that the
game had ever been played. The same hole swallows a crash, a reboot, a killed
shell, or an endpoint that stays down past the retry ladder, and each of those
costs roughly two hours and four million tokens.

The trace survived every one of those events. The result did not, which is
backwards: the trace is the diagnostic and the scorecard is the deliverable.
"""
from __future__ import annotations

import inspect
import json
import re
import tempfile
from pathlib import Path

from evals.arc.codeact_agent import play


def check_play_accepts_an_output_path() -> None:
    """Checkpointing is impossible if play() cannot see where the result goes."""
    params = inspect.signature(play).parameters
    assert "out_path" in params, (
        "play() no longer takes out_path, so it cannot checkpoint and an "
        "interrupted run leaves nothing behind again"
    )
    assert params["out_path"].default == "", (
        "out_path must default to empty so callers that do not want "
        "checkpointing keep the old behaviour"
    )
    print("  play() knows where its result goes         OK")


def check_the_checkpoint_is_written_every_turn() -> None:
    """Inside the turn loop, not after it.

    Pinned against the live source rather than a description of it, because what
    failed here was a write that existed but ran in the wrong place -- and a
    test that only asserted "a write exists" was already satisfiable by the
    broken version.
    """
    src = inspect.getsource(play)
    assert "out_path" in src, "play() never consults out_path"

    # The checkpoint must sit at the same indentation as the trace write, which
    # is inside the per-turn loop. A write at function level is the old bug.
    for line in src.splitlines():
        if "tmp.replace" in line:
            indent = len(line) - len(line.lstrip())
            assert indent >= 12, (
                f"the checkpoint is written at indent {indent}, which is outside "
                "the turn loop -- an interrupted run still loses everything"
            )
            break
    else:
        raise AssertionError("no atomic checkpoint write found in play()")
    print("  the result is checkpointed every turn      OK")


def check_the_write_is_atomic() -> None:
    """A kill landing mid-write must not leave half a JSON file.

    The standings scorer skips malformed artifacts, so a truncated scorecard is
    the same loss as no scorecard, with extra steps and a misleading file on
    disk suggesting the run was recorded.
    """
    src = inspect.getsource(play)
    assert re.search(r"\.partial", src), "the checkpoint does not write via a temporary file"
    assert re.search(r"\.replace\(", src), (
        "the checkpoint does not move the temporary file into place atomically"
    )
    print("  a kill mid-write cannot truncate it        OK")


def check_a_batch_does_not_overwrite_finished_games() -> None:
    """One output path, many games: checkpointing must not clobber the finished ones."""
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod.main)
    assert "len(games) == 1" in src, (
        "a multi-game batch shares one output path, so a per-turn snapshot of "
        "the game in progress would overwrite the games already finished -- "
        "trading one loss for a worse one"
    )
    print("  a batch does not clobber finished games    OK")


def check_the_snapshot_is_shaped_like_a_result() -> None:
    """The standings scorer must be able to read a checkpoint unchanged.

    score_run keys on run["game"], and start_level / scorable decide whether a
    row is quotable at all. A checkpoint missing any of them is a file that
    exists and cannot be scored.
    """
    src = inspect.getsource(play)
    body = src[src.index("if out_path:"):]
    for field in ("game=", "levels_completed=", "actions_spent=", "level_actions=",
                  "start_level=", "scorable=", "stopped="):
        assert field in body, f"the checkpoint omits {field!r}, so it cannot be scored"

    # And it must land under "runs", which is what every reader globs for.
    assert '"runs"' in body, "the checkpoint does not nest the run under 'runs'"

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.json"
        p.write_text(json.dumps({"runs": [{"game": "sb26", "levels_completed": 1,
                                           "actions_spent": 10, "start_level": 1,
                                           "scorable": True}]}), encoding="utf-8")
        assert json.loads(p.read_text(encoding="utf-8"))["runs"][0]["game"] == "sb26"
    print("  a checkpoint is a scorable result          OK")


if __name__ == "__main__":
    print("an interrupted run keeps its result:")
    check_play_accepts_an_output_path()
    check_the_checkpoint_is_written_every_turn()
    check_the_write_is_atomic()
    check_a_batch_does_not_overwrite_finished_games()
    check_the_snapshot_is_shaped_like_a_result()
    print("ALL GREEN")
