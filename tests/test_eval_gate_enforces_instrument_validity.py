"""
tests/test_eval_gate_enforces_instrument_validity.py

Guard for issue #171. MISSION.md states the rule as a charter obligation:

    Gate-instrument validity: a shipping gate counts only while its instrument can still
    discriminate. An eval gate whose measurement is missing, marked void, older than 14 days,
    or saturated at a perfect score is UNKNOWN: it neither blocks nor silently passes, and the
    reason is recorded on the change.

`scripts/eval-gate.ps1` disclosed saturation and checked nothing about age. The baseline in
`eval/scoreboard.json` is dated 2026-07-03, so every merge since 2026-07-17 has been gated
against a measurement the charter already considers unable to discriminate, and the gate said
nothing.

That is the defect class #203 and #206 were: a rule advertised in one place and enforced
nowhere. A gate cannot be the thing that decides whether the loop ships blind while it is
itself blind to the age of its own instrument.

UNKNOWN is deliberately not a failure. Blocking on a stale baseline would stop the very PRs
that could refresh it, so the gate must say so loudly and let the change proceed on the other
tiers.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).parent.parent
EVAL_GATE = REPO / "scripts" / "eval-gate.ps1"
SCOREBOARD = REPO / "eval" / "scoreboard.json"
UPDATER = REPO / "scripts" / "update-scoreboard.ps1"

UNKNOWN = "UNKNOWN"
MAX_AGE_DAYS = 14

# Windows ships `powershell` (5.1); Linux and macOS ship `pwsh` (Core), which is what the CI
# runners have. Probing only `powershell` made all three gate tests skip on Linux, so the suite
# exited 0 having proven nothing — and phoenix-proof correctly rejected that base as vacuous.
# The sibling file's docstring warns about exactly this: a probe that can silently erase the
# observation erases the evidence with it.
POWERSHELL_CANDIDATES = ("pwsh", "powershell")


def _powershell_exe():
    """The PowerShell executable available here, or None.

    A timeout is a loaded machine, not a missing interpreter, so it raises rather than being
    read as absence.
    """
    for exe in POWERSHELL_CANDIDATES:
        if shutil.which(exe) is None:
            continue
        try:
            subprocess.run(
                [exe, "-NoProfile", "-Command", "$PSVersionTable.PSVersion"],
                capture_output=True,
                timeout=30,
            )
            return exe
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"the {exe} availability probe timed out after 30s. That is a loaded or broken "
                "environment, not a missing interpreter. Skipping here would erase the only "
                "observation that this gate enforces its own charter (issue #171)."
            ) from exc
    return None


def _write_results(path, resolved_fraction, tasks=9):
    hits = round(resolved_fraction * tasks)
    lines = []
    for i in range(tasks):
        lines.append(json.dumps({"id": f"t{i}-A", "task": f"t{i}", "arm": "A_vanilla",
                                 "rep": 1, "f2p": 1, "p2p": 1, "resolved": 1}))
        lines.append(json.dumps({"id": f"t{i}-B", "task": f"t{i}", "arm": "B_phoenix",
                                 "rep": 1, "f2p": 1, "p2p": 1, "resolved": 1 if i < hits else 0}))
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")


def _sandbox(tmp_path, baseline_date, baseline_arm_b=0.7778, measured_arm_b=0.778):
    """A throwaway checkout with a chosen baseline date. Never touches the real scoreboard.

    The baseline defaults to 0.7778 because `_write_results` resolves 7 of 9 tasks and the gate
    rounds to four places; a baseline of 0.778 would read as a 0.0002 regression and mask what
    these tests are actually asserting.
    """
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "eval").mkdir(parents=True)
    shutil.copy(EVAL_GATE, tmp_path / "scripts" / "eval-gate.ps1")
    shutil.copy(UPDATER, tmp_path / "scripts" / "update-scoreboard.ps1")

    board = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    board["baseline"]["date"] = baseline_date
    board["baseline"]["swe_bench_lite"]["arm_b_phoenix_resolved"] = baseline_arm_b
    (tmp_path / "eval" / "scoreboard.json").write_text(
        json.dumps(board, indent=2), encoding="utf-8"
    )

    results = tmp_path / "prebuilt.jsonl"
    _write_results(results, measured_arm_b)
    return results


def _run_gate(tmp_path, results, exe):
    return subprocess.run(
        [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(tmp_path / "scripts" / "eval-gate.ps1"),
         "-PrebuiltResults", str(results),
         "-ResultsOut", str(tmp_path / "out.jsonl")],
        capture_output=True, text=True, timeout=180, cwd=str(tmp_path))


def _days_ago(days):
    import datetime
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def test_gate_reports_unknown_when_the_baseline_is_older_than_the_charter_allows(tmp_path):
    """A measurement past 14 days cannot discriminate, and the gate has to say so."""
    exe = _powershell_exe()
    if exe is None:
        pytest.skip("no PowerShell interpreter available")
    results = _sandbox(tmp_path, baseline_date=_days_ago(MAX_AGE_DAYS + 30))
    r = _run_gate(tmp_path, results, exe)
    combined = r.stdout + r.stderr
    assert UNKNOWN in combined, (
        f"a baseline {MAX_AGE_DAYS + 30} days old is UNKNOWN under MISSION.md, and the gate "
        "must disclose that rather than gate against it silently\n" + combined
    )


def test_unknown_does_not_block_the_change(tmp_path):
    """UNKNOWN neither blocks nor silently passes.

    Blocking on a stale baseline would stop the very pull requests that could refresh it.
    """
    exe = _powershell_exe()
    if exe is None:
        pytest.skip("no PowerShell interpreter available")
    results = _sandbox(tmp_path, baseline_date=_days_ago(MAX_AGE_DAYS + 30))
    r = _run_gate(tmp_path, results, exe)
    assert r.returncode == 0, (
        "UNKNOWN is a disclosure, not a rejection\n" + r.stdout + r.stderr
    )


def test_unknown_cannot_reject_a_below_baseline_measurement(tmp_path):
    """The validity guard must be load-bearing when the observed score is lower."""
    exe = _powershell_exe()
    if exe is None:
        pytest.skip("no PowerShell interpreter available")
    results = _sandbox(
        tmp_path,
        baseline_date=_days_ago(MAX_AGE_DAYS + 30),
        measured_arm_b=0.5,
    )
    r = _run_gate(tmp_path, results, exe)
    combined = r.stdout + r.stderr
    assert r.returncode == 0, (
        "an UNKNOWN instrument must abstain rather than reject a change\n" + combined
    )
    assert UNKNOWN in combined
    assert "REGRESSION" not in combined


def test_missing_measurement_is_unknown(tmp_path):
    exe = _powershell_exe()
    if exe is None:
        pytest.skip("no PowerShell interpreter available")
    results = _sandbox(tmp_path, baseline_date=_days_ago(1))
    board_path = tmp_path / "eval" / "scoreboard.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    del board["baseline"]["swe_bench_lite"]["arm_b_phoenix_resolved"]
    board_path.write_text(json.dumps(board), encoding="utf-8")
    r = _run_gate(tmp_path, results, exe)
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert "UNKNOWN: the baseline carries no Arm B measurement" in combined
    assert "ABSTAIN" in combined


def test_gate_stays_quiet_when_the_baseline_is_fresh(tmp_path):
    """The anti-noise control. Printed unconditionally the disclosure would mean nothing."""
    exe = _powershell_exe()
    if exe is None:
        pytest.skip("no PowerShell interpreter available")
    results = _sandbox(tmp_path, baseline_date=_days_ago(1))
    r = _run_gate(tmp_path, results, exe)
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert UNKNOWN not in combined, (
        "a one-day-old baseline is inside the charter window and needs no disclosure\n" + combined
    )


def test_the_shipped_scoreboard_is_currently_stale(tmp_path):
    """The condition is real here, not hypothetical.

    This is the observation that makes the guard above non-vacuous: the baseline actually in
    the repository is past the charter window right now. If a future refresh makes this test
    fail, that is the good outcome and the assertion should be inverted to a freshness check.
    """
    import datetime
    board = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    baseline_date = datetime.date.fromisoformat(board["baseline"]["date"])
    age = (datetime.date.today() - baseline_date).days
    assert age > MAX_AGE_DAYS, (
        f"the shipped baseline is {age} days old; if it has been refreshed, invert this test"
    )
