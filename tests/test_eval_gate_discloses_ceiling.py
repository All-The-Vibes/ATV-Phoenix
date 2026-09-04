"""
tests/test_eval_gate_discloses_ceiling.py

Guard for issue #142. `eval/scoreboard.json` records `arm_b_phoenix_resolved: 1.0` for
swe-bench-lite, and `scripts/eval-gate.ps1` passes whenever the measured Arm B score is at
least the baseline. A score can never exceed 1.0, so with the baseline at 1.0 the delta can
never be positive: the Tier 3 gate can detect a regression and cannot detect an improvement.

Every recorded run since 2026-07-03 has Arm B at exactly 1.0 with delta 0.0. The gate printed
`PASS: Arm B 1 >= baseline 1` each time and said nothing about the ceiling, so a reader had no
way to tell a real pass from a tie that carries no information.

The limitation changes what the gate may decide: a saturated instrument is UNKNOWN and must
abstain, while a fresh instrument with headroom accepts a tie and rejects a deliberate drop.
"""
import errno
import datetime
import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).parent.parent
EVAL_GATE = REPO / "scripts" / "eval-gate.ps1"
SCOREBOARD = REPO / "eval" / "scoreboard.json"
UPDATER = REPO / "scripts" / "update-scoreboard.ps1"

SATURATED = "SATURATED"


def _pwsh_available():
    """Report whether PowerShell can be invoked, and refuse to guess.

    The original form caught every exception and returned False, so a
    `subprocess.TimeoutExpired` from a loaded machine read as "PowerShell is not
    installed" and the gate tests below skipped themselves while the suite exited 0.

    That matters more here than in an ordinary test file. The valid-gate test below
    is the repository's observation of the Tier 3 gate rejecting a deliberately
    regressed arm and accepting an unchanged one, which is exactly what issue #171 asks
    for: "a gate never seen doing both is not evidence." A probe that can silently erase
    that observation erases the evidence with it, and the run still reports success.

    Only a genuine absence justifies a skip. A timeout is an environment failure and
    raises, so the run goes red and says why instead of quietly proving nothing.
    Same defect and same fix as issue #170 in tests/test_harvest_datapoint.py.
    """
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion"],
                       capture_output=True, timeout=30)
        return True
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return False
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "the PowerShell availability probe timed out after 30s. That is a loaded or "
            "broken environment, not a missing interpreter. Skipping here would erase the "
            "only observation that the Tier 3 gate rejects a regressed arm (issue #171)."
        ) from exc


def _write_results(path, resolved_fraction, tasks=9):
    hits = round(resolved_fraction * tasks)
    lines = []
    for i in range(tasks):
        lines.append(json.dumps({"id": f"t{i}-A", "task": f"t{i}", "arm": "A_vanilla",
                                 "rep": 1, "f2p": 1, "p2p": 1, "resolved": 1}))
        lines.append(json.dumps({"id": f"t{i}-B", "task": f"t{i}", "arm": "B_phoenix",
                                 "rep": 1, "f2p": 1, "p2p": 1, "resolved": 1 if i < hits else 0}))
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")


def _sandbox(tmp_path, baseline_arm_b, measured_arm_b, baseline_date=None):
    """A throwaway checkout with a chosen baseline. Never touches the real scoreboard."""
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "eval").mkdir(parents=True)
    shutil.copy(EVAL_GATE, tmp_path / "scripts" / "eval-gate.ps1")
    shutil.copy(UPDATER, tmp_path / "scripts" / "update-scoreboard.ps1")

    board = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    board["baseline"]["swe_bench_lite"]["arm_b_phoenix_resolved"] = baseline_arm_b
    if baseline_date is not None:
        board["baseline"]["date"] = baseline_date
    (tmp_path / "eval" / "scoreboard.json").write_text(json.dumps(board, indent=2), encoding="utf-8")

    results = tmp_path / "prebuilt.jsonl"
    _write_results(results, measured_arm_b)
    return results


def _run_gate(tmp_path, results):
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(tmp_path / "scripts" / "eval-gate.ps1"),
         "-PrebuiltResults", str(results),
         "-ResultsOut", str(tmp_path / "out.jsonl")],
        capture_output=True, text=True, timeout=120, cwd=str(tmp_path))


def test_gate_discloses_that_a_ceiling_baseline_cannot_show_improvement(tmp_path):
    if not _pwsh_available():
        pytest.skip("powershell unavailable")
    results = _sandbox(tmp_path, baseline_arm_b=1.0, measured_arm_b=1.0)
    r = _run_gate(tmp_path, results)
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert SATURATED in combined, (
        "baseline 1.0 leaves no headroom, and the gate must say so instead of printing a bare PASS\n"
        + combined
    )


def test_saturated_gate_abstains_from_a_deliberate_drop(tmp_path):
    if not _pwsh_available():
        pytest.skip("powershell unavailable")
    results = _sandbox(tmp_path, baseline_arm_b=1.0, measured_arm_b=0.5)
    r = _run_gate(tmp_path, results)
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert "UNKNOWN (SATURATED)" in combined
    assert "ABSTAIN" in combined
    assert "REGRESSION" not in combined


def test_gate_stays_quiet_when_the_baseline_has_headroom(tmp_path):
    """The anti-noise control. Printed unconditionally the disclosure would mean nothing."""
    if not _pwsh_available():
        pytest.skip("powershell unavailable")
    results = _sandbox(tmp_path, baseline_arm_b=0.778, measured_arm_b=1.0)
    r = _run_gate(tmp_path, results)
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert SATURATED not in combined, (
        "0.778 has room above it, so the ceiling warning does not apply\n" + combined
    )


def test_valid_gate_accepts_unchanged_and_rejects_regression_on_the_same_corpus(tmp_path):
    """A valid instrument must accept a tie and reject a deliberate drop for score reasons."""
    if not _pwsh_available():
        pytest.skip("powershell unavailable")
    fresh = datetime.date.today().isoformat()
    tie = _sandbox(
        tmp_path / "tie",
        baseline_arm_b=0.7778,
        measured_arm_b=0.7778,
        baseline_date=fresh,
    )
    r_tie = _run_gate(tmp_path / "tie", tie)
    assert r_tie.returncode == 0, r_tie.stdout + r_tie.stderr
    assert "PASS" in r_tie.stdout
    assert "UNKNOWN" not in r_tie.stdout

    drop = _sandbox(
        tmp_path / "drop",
        baseline_arm_b=0.7778,
        measured_arm_b=0.5,
        baseline_date=fresh,
    )
    r_drop = _run_gate(tmp_path / "drop", drop)
    combined = r_drop.stdout + r_drop.stderr
    assert r_drop.returncode == 1, combined
    assert "REGRESSION" in combined, combined
    assert "UNKNOWN" not in combined, combined


# --- issue #171: the evidence must not be able to disappear quietly ---


def test_probe_returns_false_when_powershell_is_genuinely_absent(monkeypatch):
    """A missing interpreter is the one condition that justifies skipping."""
    def _absent(*args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(subprocess, "run", _absent)
    assert _pwsh_available() is False


def test_probe_raises_when_the_probe_times_out(monkeypatch):
    """A timeout is a loaded machine, not a missing interpreter.

    Without this, a slow moment on the runner turns the three tests above into skips and
    the Tier 3 gate goes unobserved while the suite still exits 0.
    """
    def _slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["powershell"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _slow)
    with pytest.raises(RuntimeError) as caught:
        _pwsh_available()
    assert "timed out" in str(caught.value)


def test_probe_does_not_swallow_unexpected_errors(monkeypatch):
    """Anything that is neither absence nor timeout must surface, not read as absent."""
    def _broken(*args, **kwargs):
        raise OSError(errno.E2BIG, "argument list too long")

    monkeypatch.setattr(subprocess, "run", _broken)
    with pytest.raises(OSError):
        _pwsh_available()


def test_the_regression_observation_actually_runs_on_this_machine():
    """Fails if the gate evidence is being skipped on a machine that can run it.

    Issue #171 wants the Tier 3 gate observed both accepting an unchanged arm and
    rejecting a regressed one. The valid-gate test above is that
    observation, and it is guarded by `_pwsh_available`. If PowerShell is on PATH and the
    probe still says otherwise, that guard is lying and the observation is not happening.
    """
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is genuinely absent on this machine")
    assert _pwsh_available() is True
