"""Does restarting the loop destroy the evidence of the runs before it?

`auto_corpus.py` seeds `wave = 0` on every start and never reads the state file it
writes at the end of every wave. So each restart replays tags from ev1, and every
artifact a previous run wrote under that tag -- scorecard and trace -- is overwritten
by the new one.

This is not hypothetical. The ledger records 4 restarts and 6 reused tags:

  ev1  used 2026-08-14T17:27 and again 2026-08-15T00:43
  ev2  used 2026-08-14T18:28 and again 2026-08-15T01:42
  ...through ev6

The trace loss is bad. The SCORE loss is worse: `standings.py` takes the best run per
game across scorecards, so a strong ev3 result replaced by a weak ev3 result lowers
the corpus permanently and silently. There is no record that the better run existed.

Same defect class as the rest of this session -- machinery that writes state nothing
reads. `STATE.write_text(...)` runs every single wave and has no consumer.

Checks:
  - the wave counter is seeded from what is already on disk, not from 0
  - the seed survives a state file that is missing or corrupt (a crash mid-write must
    not silently reset the counter to 1 and start overwriting again)
  - a tag that already has artifacts on disk is never reused

Free. No game, no API calls.
"""
from __future__ import annotations

import ast
import inspect
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _mod():
    import evals.arc.auto_corpus as m
    return m


def check_counter_is_seeded_from_disk() -> tuple[bool, str]:
    m = _mod()
    if not hasattr(m, "resume_wave"):
        return False, (
            "there is no resume_wave(): main() sets wave = 0 unconditionally, so every "
            "restart replays ev1, ev2, ... over the previous run's artifacts. Measured: "
            "4 restarts, tags ev1-ev6 each used twice."
        )
    return True, "the wave counter is recoverable from disk"


def check_it_actually_resumes() -> tuple[bool, str]:
    """Behavioural: hand it a ledger ending at wave 19 and demand 20."""
    m = _mod()
    if not hasattr(m, "resume_wave"):
        return False, "no resume_wave() to exercise"
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "ledger.jsonl"
        led.write_text("".join(
            json.dumps({"event": "wave", "wave": w, "tag": f"ev{w}"}) + "\n"
            for w in range(1, 20)
        ), encoding="utf-8")
        got = m.resume_wave(led, results=Path(d))
    if got != 19:
        return False, f"ledger ends at wave 19 but resume_wave returned {got}"
    return True, "a ledger ending at wave 19 resumes at 19, so the next tag is ev20"


def check_corrupt_state_does_not_reset() -> tuple[bool, str]:
    """A half-written file must not silently hand back 0 and start overwriting."""
    m = _mod()
    if not hasattr(m, "resume_wave"):
        return False, "no resume_wave() to exercise"
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "ledger.jsonl"
        led.write_text(
            json.dumps({"event": "wave", "wave": 7, "tag": "ev7"}) + "\n"
            + '{"event": "wave", "wave": 8, "tag": "ev8"' + "\n",   # truncated line
            encoding="utf-8")
        got = m.resume_wave(led, results=Path(d))
    if got < 7:
        return False, (
            f"a truncated final line dropped the counter to {got}; the next wave would "
            f"overwrite ev{got + 1}"
        )
    return True, f"a corrupt trailing line still resumes at {got}"


def check_missing_ledger_is_not_a_reset() -> tuple[bool, str]:
    """No ledger is a genuinely fresh start; that one IS allowed to be 0."""
    m = _mod()
    if not hasattr(m, "resume_wave"):
        return False, "no resume_wave() to exercise"
    with tempfile.TemporaryDirectory() as d:
        got = m.resume_wave(Path(d) / "nope.jsonl", results=Path(d))
    if got != 0:
        return False, f"a genuinely empty workspace should start at 0, got {got}"
    return True, "an absent ledger starts at 0, which is the only safe reset"


def check_main_uses_it() -> tuple[bool, str]:
    """Not "is resume_wave mentioned" -- is the counter actually SET from its return.

    The first version accepted `wave = resume_wave() and 0`, which calls the function,
    discards the answer, and reinstates the exact bug. Checking that a name appears is
    how eight checks went vacuous this session; the assignment has to be the thing that
    is verified.
    """
    src = inspect.getsource(_mod().main)
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "wave" for t in node.targets):
            continue
        v = node.value
        called = isinstance(v, ast.Call) and (
            (isinstance(v.func, ast.Name) and v.func.id == "resume_wave")
            or (isinstance(v.func, ast.Attribute) and v.func.attr == "resume_wave"))
        if called:
            return True, "wave is assigned directly from resume_wave()"
    return False, (
        "the wave counter is not assigned straight from resume_wave(). Calling it and "
        "discarding the result restores the original bug: every restart replays ev1 and "
        "overwrites the previous run's scorecards."
    )


def check_a_dead_wave_is_not_reused() -> tuple[bool, str]:
    """A wave that STARTED and died leaves artifacts the ledger never records.

    The ledger only gets a row when a wave finishes. The original loop began wave 20 at
    13:21, ran ka59 for 53 turns, and died when its shell exited -- writing
    trace-ka59-ev20.jsonl and two scorecards, and recording nothing. Resuming from the
    ledger alone therefore picked ev20 again and appended a second run into the same
    trace, which is what made level_monotonic_check and reset_check read [1,2,3,1,2,3]
    and report a game reset that never happened.

    So the resume point is the highest wave with EVIDENCE on disk, not the highest wave
    with a ledger row.
    """
    m = _mod()
    if not hasattr(m, "resume_wave"):
        return False, "no resume_wave() to exercise"
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        led = d / "ledger.jsonl"
        led.write_text(json.dumps({"event": "wave", "wave": 19, "tag": "ev19"}) + "\n",
                       encoding="utf-8")
        # wave 20 started and died: artifacts, no ledger row
        (d / "trace-ka59-ev20.jsonl").write_text("{}\n", encoding="utf-8")
        (d / "g50t-ev20.json").write_text("{}", encoding="utf-8")
        got = m.resume_wave(led, results=d)
    if got < 20:
        return False, (
            f"resumed at {got} while ev20 artifacts are already on disk; the next wave "
            f"would append into trace-ka59-ev20.jsonl and corrupt it"
        )
    return True, "a started-but-unrecorded wave is stepped over, not reused"


CHECKS = [
    ("the counter can be recovered from disk", check_counter_is_seeded_from_disk),
    ("a ledger at wave 19 resumes at 19", check_it_actually_resumes),
    ("a corrupt trailing line does not reset", check_corrupt_state_does_not_reset),
    ("an absent ledger starts at 0", check_missing_ledger_is_not_a_reset),
    ("a dead wave's tag is not reused", check_a_dead_wave_is_not_reused),
    ("main() actually calls it", check_main_uses_it),
]


def main() -> int:
    failures = 0
    for title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {title}\n       {detail}")
        failures += not ok
    print("-" * 70)
    print("wave resume: ALL PASS" if not failures else f"wave resume: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
