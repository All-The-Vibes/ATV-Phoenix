"""
tests/test_scoreboard.py
Acceptance tests for eval/scoreboard.json + scripts/update-scoreboard.ps1 (issue #37).
"""
import json
import pathlib
import subprocess
import tempfile
import shutil
import os

REPO = pathlib.Path(__file__).parent.parent
SCOREBOARD = REPO / "eval" / "scoreboard.json"
UPDATE_SCRIPT = REPO / "scripts" / "update-scoreboard.ps1"


def test_scoreboard_exists():
    assert SCOREBOARD.exists(), f"Missing: {SCOREBOARD}"


def test_scoreboard_schema():
    data = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    assert data.get("_schema") == "1.0"
    assert "baseline" in data
    assert "runs" in data
    assert isinstance(data["runs"], list)


def test_baseline_has_required_fields():
    data = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    b = data["baseline"]["swe_bench_lite"]
    assert "arm_b_phoenix_resolved" in b
    assert "arm_a_vanilla_resolved" in b
    assert "tasks" in b
    assert 0.0 <= b["arm_b_phoenix_resolved"] <= 1.0
    assert 0.0 <= b["arm_a_vanilla_resolved"] <= 1.0


def test_baseline_arm_b_at_least_arm_a():
    """Phoenix arm must be >= vanilla arm in the baseline (thesis check)."""
    data = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    b = data["baseline"]["swe_bench_lite"]
    assert b["arm_b_phoenix_resolved"] >= b["arm_a_vanilla_resolved"], (
        f"Arm B ({b['arm_b_phoenix_resolved']}) must be >= Arm A ({b['arm_a_vanilla_resolved']})"
    )


def test_update_scoreboard_no_regression(tmp_path):
    """update-scoreboard.ps1 exits 0 when Arm B score matches baseline."""
    _run_update_test(tmp_path, arm_b=1.0, arm_a=0.778, expect_exit=0)


def test_update_scoreboard_regression_exits_1(tmp_path):
    """update-scoreboard.ps1 exits 1 when Arm B drops below baseline."""
    _run_update_test(tmp_path, arm_b=0.5, arm_a=0.778, expect_exit=1)


def test_update_scoreboard_improvement_exits_0(tmp_path):
    """update-scoreboard.ps1 exits 0 when Arm B improves above baseline."""
    _run_update_test(tmp_path, arm_b=1.0, arm_a=0.9, expect_exit=0)


def test_readme_score_tracker_section():
    """README.md must contain a Score Tracker section with the baseline values."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## Score Tracker" in readme, "README must have a ## Score Tracker section"
    data = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    b = data["baseline"]["swe_bench_lite"]
    assert str(b["arm_b_phoenix_resolved"]) in readme, (
        f"README Score Tracker must show baseline Arm B value {b['arm_b_phoenix_resolved']}"
    )


# --- helpers ---

def _make_results_jsonl(tmp_path, arm_b_resolved, arm_a_resolved, tasks=9):
    lines = []
    for i in range(tasks):
        lines.append(json.dumps({
            "id": f"task-{i}-A-1", "task": f"task-{i}", "arm": "A_vanilla",
            "rep": 1, "f2p": 1, "p2p": 1,
            "resolved": 1 if i < round(arm_a_resolved * tasks) else 0
        }))
        lines.append(json.dumps({
            "id": f"task-{i}-B-1", "task": f"task-{i}", "arm": "B_phoenix",
            "rep": 1, "f2p": 1, "p2p": 1,
            "resolved": 1 if i < round(arm_b_resolved * tasks) else 0
        }))
    p = tmp_path / "results.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _run_update_test(tmp_path, arm_b, arm_a, expect_exit):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    results = _make_results_jsonl(tmp_path, arm_b, arm_a)
    # Copy scoreboard to tmp
    sb_copy = tmp_path / "scoreboard.json"
    shutil.copy(SCOREBOARD, sb_copy)
    # Copy README to tmp
    readme_copy = tmp_path / "README.md"
    readme_src = REPO / "README.md"
    if readme_src.exists():
        shutil.copy(readme_src, readme_copy)
    else:
        readme_copy.write_text("# ATV-Phoenix\n", encoding="utf-8")
    r = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(UPDATE_SCRIPT),
         "-ResultsFile", str(results), "-ScoreboardFile", str(sb_copy),
         "-Trigger", "test"],
        capture_output=True, text=True, timeout=30,
        cwd=tmp_path
    )
    assert r.returncode == expect_exit, (
        f"Expected exit {expect_exit}, got {r.returncode}\n{r.stdout}\n{r.stderr}"
    )


def _pwsh_available():
    try:
        subprocess.run(["powershell", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False
