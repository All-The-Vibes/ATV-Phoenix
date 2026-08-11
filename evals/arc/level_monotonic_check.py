"""Does "a level was cleared" mean a level was cleared?

The SDK's `levels_completed` is not a monotone level counter. On some games it falls
back and climbs again inside a single level, and the harness used to read every upward
tick as a fresh level:

    if self._frame.levels_completed > before_levels:   # WRONG

Measured on `trace-s5i5-b.jsonl`, that fired nine times for a run that cleared two
levels. Seven of those nine told the agent "LEVEL 1 CLEARED. The board below is a
DIFFERENT level" while it was standing on level 3. Each one threw away the level notes
and the retractions it had just paid actions to learn, and each one restarted the action
mark -- so `level_actions` came out as nine entries and the scorer, which slices
`[:levels_completed]`, charged level 2 the last 49 of the 375 actions it really cost.

`reset_check` already watched for the level count falling and never saw it, because it
reads the trace's per-turn `levels` field. The oscillation happens BETWEEN actions,
inside a single turn, so a per-turn sample is monotone even while the counter is not.
This check reads at the resolution where the damage is visible: the LevelCleared message
itself, which carries the level number the harness believed at that instant.

The fix is to gate on the high-water mark. A new maximum is the only reading that means
"a level I had never finished before" -- which is exactly what RHAE credits, since the
scorecard reports `env.best`. It also makes `len(level_actions) == levels_completed`
true by construction, and it charges a level every action spent on it including replays,
which is the honest reading: replaying a board buys back the board, never the budget.

Run: python -m evals.arc.level_monotonic_check
     python evals/arc/level_monotonic_check.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # tolerate `python evals/arc/level_monotonic_check.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

AGENT = Path("evals/arc/codeact_agent.py")
RESULTS = Path("eval/arc-results")
CLEARED = re.compile(r"LEVEL (\d+) CLEARED in (\d+) actions")

# Read from the harness rather than restated here, so bumping the version in one place
# cannot leave this check silently binding the wrong generation of artifact.
from evals.arc.codeact_agent import HARNESS_VERSION as CURRENT_HARNESS  # noqa: E402


def _fail(msg: str) -> str:
    return f"FAIL  {msg}"


def _ok(msg: str) -> str:
    return f"ok    {msg}"


def _step_source() -> str:
    src = AGENT.read_text(encoding="utf-8")
    i = src.find("self.best = max(self.best, self._frame.levels_completed)")
    if i < 0:
        return ""
    return src[i - 400 : i + 3200]


def check_gate_is_the_high_water_mark() -> tuple[bool, list[str]]:
    """The level-transition branch must compare against the best, not the last frame."""
    body = _step_source()
    if not body:
        return False, [_fail("could not locate the level-transition branch in Env._step")]

    if re.search(r"if self\._frame\.levels_completed > before_levels\s*:", body):
        return False, [
            _fail(
                "the branch still fires on any upward tick of a counter that is not "
                "monotone -- a replay is being credited as a new level"
            )
        ]
    if not re.search(r"if self\.best > before_best\s*:", body):
        return False, [_fail("the branch no longer gates on a new high-water mark")]
    out = [_ok("the transition fires only on a new high-water mark")]

    # The snapshot has to be taken BEFORE best is advanced, or the comparison is
    # against a value that already includes this frame and can never be greater.
    snap = body.find("before_best = self.best")
    adv = body.find("self.best = max(self.best, self._frame.levels_completed)")
    if snap < 0:
        return False, [_fail("before_best is never captured")]
    if snap > adv:
        return False, [
            _fail("before_best is captured after best is advanced; the branch is dead")
        ]
    out.append(_ok("before_best is captured before best advances"))

    # The message the agent reads must name the level actually reached.
    if re.search(r"LEVEL \{self\._frame\.levels_completed\} CLEARED", body):
        return False, [
            _fail("the LevelCleared message still names a non-monotone counter")
        ]
    if not re.search(r"LEVEL \{self\.best\} CLEARED", body):
        return False, [_fail("the LevelCleared message does not name the level reached")]
    out.append(_ok("the message names the level reached, not the raw counter"))
    return True, out


def check_attribution_on_a_replay() -> tuple[bool, list[str]]:
    """Replay the real s5i5 tick sequence through both rules and compare."""
    # (levels_completed after the action, actions spent so far) at each upward tick,
    # taken from trace-s5i5-b.jsonl. The counter reads 1,1,1,2,1,1,1,1,1.
    #
    # Every row here is a moment the OLD rule fired -- that is how they were found.
    # The counter fell back between them, and those falls are not in the fixture, so
    # the old rule cannot be re-derived by comparing one row to the row before it.
    # It is one entry per row, by construction.
    ticks = [(1, 107), (1, 156), (1, 175), (2, 482), (1, 684), (1, 706), (1, 728),
             (1, 885), (1, 1215)]

    old, mark = [], 0
    for _value, spent in ticks:
        old.append(spent - mark)
        mark = spent

    new, mark, best = [], 0, 0
    for value, spent in ticks:
        if value > best:
            best = value
            new.append(spent - mark)
            mark = spent

    if len(old) <= 2:
        return False, [_fail("the fixture no longer reproduces the over-counting")]
    out = [_ok(f"the old rule produced {len(old)} entries for 2 levels: {old}")]

    if len(new) != 2:
        return False, [_fail(f"the new rule produced {len(new)} entries, expected 2")]
    if new != [107, 375]:
        return False, [_fail(f"per-level attribution is {new}, expected [107, 375]")]
    out.append(_ok(f"the new rule produces one entry per level: {new}"))
    out.append(
        _ok("level 2 is charged all 375 actions it cost, not the last 49 of them")
    )
    return True, out


def _harness_of(run: dict, blob) -> int:
    """Which harness wrote this record. Unstamped means version 1, by definition."""
    if isinstance(run, dict) and "harness" in run:
        return int(run.get("harness") or 1)
    if isinstance(blob, dict) and "harness" in blob:
        return int(blob.get("harness") or 1)
    return 1


def _trace_harness(trace: Path) -> int:
    """A trace inherits the stamp of the scorecard written beside it, same run."""
    card = trace.with_name(trace.name[len("trace-"):]).with_suffix(".json")
    try:
        blob = json.loads(card.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    runs = blob if isinstance(blob, list) else (blob.get("runs") or [])
    stamps = [_harness_of(r, blob) for r in runs if isinstance(r, dict)]
    return min(stamps) if stamps else _harness_of({}, blob)


def check_scorecards_hold_the_invariant() -> tuple[bool, list[str]]:
    """On disk, every run must charge exactly one action count per cleared level.

    Scoped to cards this harness wrote. A version-1 card recorded a level count the
    harness had already mis-attributed, and nothing readable in the file can undo that
    -- the actions were charged to the wrong level before it was ever written. Failing
    on them forever would only train the reader to ignore a red check, so they are
    QUARANTINED: named, counted, and excluded from the verdict. The invariant itself is
    not relaxed by one inch for anything version 2 produces.
    """
    cards = sorted(RESULTS.glob("*.json"))
    if not cards:
        return True, ["skip  no scorecards on disk"]

    seen, broken, legacy = 0, [], []
    for path in cards:
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs = blob if isinstance(blob, list) else (blob.get("runs") or [])
        for run in runs:
            if not isinstance(run, dict):
                continue
            per_level = run.get("level_actions")
            if per_level is None:
                continue
            done = run.get("levels_completed", 0)
            if len(per_level) == done:
                seen += 1
                continue
            entry = (f"{path.name} ({run.get('game')}): "
                     f"{len(per_level)} entries for {done} levels")
            if _harness_of(run, blob) < CURRENT_HARNESS:
                legacy.append(entry)
            else:
                broken.append(entry)

    if broken:
        lines = [_fail("level_actions disagrees with levels_completed:")]
        lines += [f"        {b}" for b in broken[:10]]
        return False, lines
    out = [_ok(f"{seen} recorded run(s) charge one action count per cleared level")]
    if legacy:
        out.append(f"        quarantined: {len(legacy)} pre-v{CURRENT_HARNESS} card(s) "
                   f"whose attribution cannot be trusted -- re-run to replace")
        out += [f"          {b}" for b in legacy[:10]]
    return True, out


def check_traces_never_reclear_a_level() -> tuple[bool, list[str]]:
    """No trace may announce the same level twice, or a level below one already announced."""
    traces = sorted(RESULTS.glob("trace-*.jsonl"))
    if not traces:
        return True, ["skip  no traces on disk"]

    examined, offenders, legacy = 0, [], []
    for path in traces:
        announced: list[int] = []
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    # json-encode first: the output carries raw newlines and quotes.
                    for m in CLEARED.finditer(json.dumps(row.get("output", ""))):
                        announced.append(int(m.group(1)))
        except OSError:
            continue
        if not announced:
            continue
        examined += 1
        for a, b in zip(announced, announced[1:]):
            if b <= a:
                entry = f"{path.name}: announced {announced}"
                # A trace carries no stamp of its own, so it inherits the verdict of
                # the scorecard written beside it -- same run, same harness.
                if _trace_harness(path) < CURRENT_HARNESS:
                    legacy.append(entry)
                else:
                    offenders.append(entry)
                break

    if not examined:
        return True, ["skip  no trace announced a cleared level"]
    if offenders:
        lines = [
            _fail(
                "a trace announced a level it had already cleared -- the agent was told "
                "its board changed when it had not:"
            )
        ]
        lines += [f"        {o}" for o in offenders[:6]]
        lines.append(
            f"        (these were written by harness v{CURRENT_HARNESS}, which is "
            "supposed to make this impossible -- the gate has regressed)"
        )
        return False, lines
    out = [_ok(f"{examined} recorded run(s) announced each level once, in ascending order")]
    if legacy:
        out.append(f"        quarantined: {len(legacy)} pre-v{CURRENT_HARNESS} trace(s) "
                   f"whose level announcements were made by the broken gate")
        out += [f"          {o}" for o in legacy[:6]]
    return True, out


def main() -> int:
    checks = (
        ("the gate is the high-water mark", check_gate_is_the_high_water_mark),
        ("attribution survives a replay", check_attribution_on_a_replay),
        ("scorecards hold the invariant", check_scorecards_hold_the_invariant),
        ("traces never re-clear a level", check_traces_never_reclear_a_level),
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
