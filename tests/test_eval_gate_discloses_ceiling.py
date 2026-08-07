"""
tests/test_eval_gate_discloses_ceiling.py

Guard for issue #142. `eval/scoreboard.json` records `arm_b_phoenix_resolved: 1.0` for
swe-bench-lite, and `scripts/eval-gate.ps1` passes whenever the measured Arm B score is at
least the baseline. A score can never exceed 1.0, so with the baseline at 1.0 the delta can
never be positive: the Tier 3 gate can detect a regression and cannot detect an improvement.

Every recorded run since 2026-07-03 has Arm B at exactly 1.0 with delta 0.0. The gate printed
`PASS: Arm B 1 >= baseline 1` each time and said nothing about the ceiling, so a reader had no
way to tell a real pass from a tie that carries no information.

This is the same disclosure fix #150 shipped for the OKF eval. Exit codes do not change here,
because the limitation is in what the number can show, not in what the gate should allow.
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

SATURATED = "SATURATED"


def _pwsh_available():
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion"],
                       capture_output=True, timeout=15)
        return True
    except Exception:
        return False


def _write_results(path, resolved_fraction, tasks=9):
    hits = round(resolved_fraction * tasks)
    lines = []
    for i in range(tasks):
        lines.append(json.dumps({"id": f"t{i}-A", "task": f"t{i}", "arm": "A_vanilla",
                                 "rep": 1, "f2p": 1, "p2p": 1, "resolved": 1}))
        lines.append(json.dumps({"id": f"t{i}-B", "task": f"t{i}", "arm": "B_phoenix",
                                 "rep": 1, "f2p": 1, "p2p": 1, "resolved": 1 if i < hits else 0}))
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")


def _sandbox(tmp_path, baseline_arm_b, measured_arm_b):
    """A throwaway checkout with a chosen baseline. Never touches the real scoreboard."""
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "eval").mkdir(parents=True)
    shutil.copy(EVAL_GATE, tmp_path / "scripts" / "eval-gate.ps1")
    shutil.copy(UPDATER, tmp_path / "scripts" / "update-scoreboard.ps1")

    board = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    board["baseline"]["swe_bench_lite"]["arm_b_phoenix_resolved"] = baseline_arm_b
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


def test_exit_codes_are_unchanged_by_the_disclosure(tmp_path):
    """Disclosure only. A ceiling baseline must still pass on a tie and still fail on a drop."""
    if not _pwsh_available():
        pytest.skip("powershell unavailable")
    tie = _sandbox(tmp_path / "tie", baseline_arm_b=1.0, measured_arm_b=1.0)
    r_tie = _run_gate(tmp_path / "tie", tie)
    assert r_tie.returncode == 0, r_tie.stdout + r_tie.stderr

    drop = _sandbox(tmp_path / "drop", baseline_arm_b=1.0, measured_arm_b=0.5)
    r_drop = _run_gate(tmp_path / "drop", drop)
    combined = r_drop.stdout + r_drop.stderr
    assert r_drop.returncode == 1, combined
    assert "REGRESSION" in combined, combined
