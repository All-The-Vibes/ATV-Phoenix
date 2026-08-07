"""
tests/test_proof_status.py

Guard for issue #138. Actions runs on Copilot-authored pull requests are held at conclusion
`action_required` and never execute, so a merge can rest on a person remembering to run the
checks by hand. `scripts/proof_status.py` answers whether the proofs for a head SHA actually
ran. These tests use recorded payload shapes, so they need no network and no GitHub token.

The `action_required` fixture below is the shape observed on 2026-08-01 for branch
copilot/atv-86-e2e-hybrid-mission.
"""
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "proof_status.py"

sys.path.insert(0, str(REPO / "scripts"))
import proof_status  # noqa: E402


def run(name, conclusion, status="completed"):
    return {"name": name, "status": status, "conclusion": conclusion}


def test_script_exists():
    assert SCRIPT.exists(), f"missing: {SCRIPT}"


def test_held_run_is_not_a_pass():
    """The whole point. action_required means queued and never executed."""
    ok, problems = proof_status.evaluate(
        [run("Phoenix proof", "action_required"), run("Connector proof", "action_required")],
        ["src/lease.rs"],
    )
    assert ok is False
    assert any("action_required" in p for p in problems), problems


def test_missing_run_is_not_a_pass():
    ok, problems = proof_status.evaluate([], ["README.md"])
    assert ok is False
    assert any("no run recorded" in p for p in problems), problems


def test_both_green_passes_when_connector_paths_touched():
    ok, problems = proof_status.evaluate(
        [run("Phoenix proof", "success"), run("Connector proof", "success")],
        ["src/mission.rs", "Cargo.toml"],
    )
    assert ok is True, problems


def test_connector_proof_not_required_for_a_docs_change():
    """A docs pull request legitimately gets no Connector proof, because of its paths: block.

    Without this, the checker would flag every docs change and get switched off.
    """
    ok, problems = proof_status.evaluate([run("Phoenix proof", "success")], ["docs/journey.md"])
    assert ok is True, problems


def test_connector_proof_required_once_a_watched_path_changes():
    """Same input as the docs case except for one file. That one file must flip the verdict."""
    ok, problems = proof_status.evaluate([run("Phoenix proof", "success")], ["phoenix_learn/gepa.py"])
    assert ok is False
    assert any("Connector proof" in p for p in problems), problems


def test_phoenix_proof_is_required_even_with_no_changed_files():
    ok, _ = proof_status.evaluate([run("Connector proof", "success")], [])
    assert ok is False


def test_failure_conclusion_is_not_a_pass():
    ok, problems = proof_status.evaluate([run("Phoenix proof", "failure")], ["README.md"])
    assert ok is False
    assert any("failure" in p for p in problems), problems


def test_queued_run_is_not_a_pass():
    ok, _ = proof_status.evaluate(
        [run("Phoenix proof", None, status="queued")], ["README.md"]
    )
    assert ok is False


def _cli(tmp_path, check_runs, changed_files):
    runs_file = tmp_path / "runs.json"
    files_file = tmp_path / "files.json"
    runs_file.write_text(json.dumps({"check_runs": check_runs}), encoding="utf-8")
    files_file.write_text(json.dumps(changed_files), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check-runs", str(runs_file),
         "--changed-files", str(files_file)],
        capture_output=True, text=True, timeout=60,
    )


def test_cli_exits_1_on_a_held_run(tmp_path):
    r = _cli(tmp_path, [run("Phoenix proof", "action_required")], ["src/lease.rs"])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "gated by memory" in r.stdout, r.stdout


def test_cli_exits_0_when_the_proofs_ran(tmp_path):
    r = _cli(tmp_path, [run("Phoenix proof", "success"), run("Connector proof", "success")],
             ["src/lease.rs"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout, r.stdout


def test_cli_exits_2_on_unreadable_input(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-runs", str(tmp_path / "nope.json"),
         "--changed-files", str(tmp_path / "also-nope.json")],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 2, r.stdout + r.stderr


@pytest.mark.parametrize("path,expected", [
    ("src/lease.rs", True),
    ("phoenix_learn/events.py", True),
    ("Cargo.lock", True),
    ("tests/test_phoenix_learn.py", True),
    (".github/workflows/connector-proof.yml", True),
    ("docs/journey.md", False),
    ("README.md", False),
    ("tests/test_scoreboard.py", False),
])
def test_connector_path_matching(path, expected):
    assert proof_status.matches_connector_paths([path]) is expected


def test_path_patterns_match_the_workflow_file():
    """If connector-proof.yml's paths: block moves, this table goes stale and lies."""
    wf = (REPO / ".github" / "workflows" / "connector-proof.yml").read_text(encoding="utf-8")
    for pattern in proof_status.CONNECTOR_PATHS:
        assert f'"{pattern}"' in wf or f"'{pattern}'" in wf or f"- {pattern}" in wf, (
            f"{pattern} is in proof_status.CONNECTOR_PATHS but not in connector-proof.yml"
        )
