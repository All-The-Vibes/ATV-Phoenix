"""tests/test_north_star_runner.py - acceptance tests for scripts/run-north-star.ps1 (issue #36)."""
import json, pathlib, subprocess, shutil, tempfile

REPO = pathlib.Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "run-north-star.ps1"
SCOREBOARD = REPO / "eval" / "scoreboard.json"

def pwsh(args, cwd=None, timeout=30):
    return subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)] + args,
        capture_output=True, text=True, timeout=timeout, cwd=str(cwd or REPO)
    )

def pwsh_ok():
    try:
        subprocess.run(["powershell", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def test_script_exists():
    assert SCRIPT.exists(), f"Missing: {SCRIPT}"


def test_eval_northstar_dir_exists():
    assert (REPO / "eval" / "north-star").exists()


def test_dry_run_exits_0():
    """--DryRun must exit 0 without touching Azure."""
    if not pwsh_ok(): import pytest; pytest.skip("pwsh unavailable")
    r = pwsh(["-DryRun"])
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "DRY RUN" in r.stdout


def test_vm_size_flag_present():
    """Script must have a -VmSize param (Standard_D16s_v5 default)."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "VmSize" in src
    assert "Standard_D16s_v5" in src


def test_ephemeral_delete_in_script():
    """Script must delete the resource group after the run (no orphaned VMs)."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "group delete" in src


def test_regression_detection_threshold():
    """Script must warn on >2pp regression (not silently accept)."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "0.02" in src or "2pp" in src.lower() or ">2" in src


def test_scores_committed_to_eval_dir():
    """Script must commit results to eval/north-star/YYYY-MM-DD/."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "north-star" in src
    assert "git" in src and "commit" in src


def test_scoreboard_north_star_baseline_nullable():
    """scoreboard.json baseline.north_star may be null (not yet run) -- that is valid."""
    data = json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))
    # north_star key may be null/missing -- that's fine pre-first-run
    ns = data.get("baseline", {}).get("north_star")
    assert ns is None or isinstance(ns, dict), f"north_star must be null or a dict, got {ns}"