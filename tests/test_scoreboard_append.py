"""
tests/test_scoreboard_append.py

Regression tests for issue #140: scripts/update-scoreboard.ps1 defaulted its
-ScoreboardFile parameter to the bare cwd-relative literal "eval\\scoreboard.json".
PowerShell resolves that against the CALLER'S current working directory, not the
repository. scripts/eval-gate.ps1 (the Tier 3 merge gate) invokes the updater
without -ScoreboardFile from scratch worktrees and other directories, so the
append either landed somewhere unintended or the script exited 2 ("Scoreboard
not found") with the output swallowed by Out-Null. The runs array in
eval/scoreboard.json therefore stopped growing.

The fix makes the default resolve against the repository root (the parent of the
scripts directory the script lives in) via $PSScriptRoot. These tests prove that
property: the load-bearing test runs the script from a DIFFERENT cwd than the
checkout and asserts the checkout scoreboard still got one appended run.

These tests never write to the real repo eval/scoreboard.json; a throwaway copy
under pytest tmp_path is what gets mutated.
"""
import json
import pathlib
import shutil
import subprocess

REPO = pathlib.Path(__file__).parent.parent
SCOREBOARD = REPO / "eval" / "scoreboard.json"
UPDATE_SCRIPT = REPO / "scripts" / "update-scoreboard.ps1"


def _pwsh_available():
    try:
        subprocess.run(["powershell", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _load_runs(path):
    raw = pathlib.Path(path).read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8")
    return json.loads(raw)["runs"]


def _write_results(path):
    """Nine tasks per arm. Every B_phoenix row is resolved=1 so Arm B equals the
    scoreboard baseline (1.0); a lower fraction would make the script exit 1 as a
    regression instead of appending. Arm A is a mix and does not gate."""
    lines = []
    for i in range(9):
        lines.append(json.dumps({
            "id": "task-%d-A-1" % i, "task": "task-%d" % i, "arm": "A_vanilla",
            "rep": 1, "f2p": 1, "p2p": 1,
            "resolved": 1 if i < 7 else 0,
        }))
        lines.append(json.dumps({
            "id": "task-%d-B-1" % i, "task": "task-%d" % i, "arm": "B_phoenix",
            "rep": 1, "f2p": 1, "p2p": 1,
            "resolved": 1,
        }))
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")


def test_default_scoreboard_resolves_to_repo_root_not_cwd(tmp_path):
    """Load-bearing proof for issue #140.

    Build a fake checkout that holds the copied script and scoreboard, then run
    the COPIED script from a separate, unrelated working directory with NO
    -ScoreboardFile argument. The default must resolve against the script's own
    repo root and append exactly one run to the checkout scoreboard. Running from
    a different cwd than the checkout is the load-bearing part: from the checkout
    root the broken code would also pass and prove nothing.
    """
    if not _pwsh_available():
        import pytest
        pytest.skip("PowerShell not available")

    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "eval").mkdir(parents=True)
    script_copy = checkout / "scripts" / "update-scoreboard.ps1"
    board_copy = checkout / "eval" / "scoreboard.json"
    shutil.copy(UPDATE_SCRIPT, script_copy)
    shutil.copy(SCOREBOARD, board_copy)

    results = tmp_path / "results.jsonl"
    _write_results(results)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    before = len(_load_runs(board_copy))
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(script_copy),
         "-ResultsFile", str(results), "-Trigger", "test"],
        capture_output=True, text=True, timeout=60,
        cwd=str(elsewhere),
    )
    assert r.returncode == 0, (
        "Expected exit 0, got %d\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (r.returncode, r.stdout, r.stderr)
    )
    after = len(_load_runs(board_copy))
    assert after == before + 1, (
        "Expected run count %d -> %d, got %d. The default -ScoreboardFile did "
        "not resolve to the checkout eval dir when run from a different cwd.\n"
        "STDOUT:\n%s\nSTDERR:\n%s"
        % (before, before + 1, after, r.stdout, r.stderr)
    )


def test_scoreboard_default_references_psscriptroot():
    """Structural guard against a silent revert: the $ScoreboardFile default must
    not be a bare cwd-relative literal; it must resolve via $PSScriptRoot."""
    text = UPDATE_SCRIPT.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8")
    marker = "$ScoreboardFile"
    assert marker in text, "param $ScoreboardFile not found in update-scoreboard.ps1"
    start = text.index(marker)
    end = text.index("$Trigger", start)
    default_segment = text[start:end]
    assert "PSScriptRoot" in default_segment, (
        "The $ScoreboardFile default must resolve against the repo root via "
        "$PSScriptRoot, not the caller cwd. Got: %r" % default_segment
    )


def test_explicit_scoreboard_argument_still_overrides(tmp_path):
    """Regression guard: an explicitly passed -ScoreboardFile must still win over
    the default (tests/test_scoreboard.py depends on this)."""
    if not _pwsh_available():
        import pytest
        pytest.skip("PowerShell not available")

    board_copy = tmp_path / "explicit_scoreboard.json"
    shutil.copy(SCOREBOARD, board_copy)
    results = tmp_path / "results.jsonl"
    _write_results(results)

    before = len(_load_runs(board_copy))
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(UPDATE_SCRIPT),
         "-ResultsFile", str(results),
         "-ScoreboardFile", str(board_copy),
         "-Trigger", "test"],
        capture_output=True, text=True, timeout=60,
        cwd=str(tmp_path),
    )
    assert r.returncode == 0, (
        "Expected exit 0, got %d\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (r.returncode, r.stdout, r.stderr)
    )
    after = len(_load_runs(board_copy))
    assert after == before + 1, (
        "Explicit -ScoreboardFile was not honored: run count %d -> %d.\n"
        "STDOUT:\n%s\nSTDERR:\n%s"
        % (before, after, r.stdout, r.stderr)
    )
