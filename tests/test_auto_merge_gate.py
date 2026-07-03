"""tests/test_auto_merge_gate.py — acceptance tests for scripts/eval-gate.ps1 (issue #35)."""
import json, pathlib, subprocess, shutil

REPO = pathlib.Path(__file__).parent.parent
EVAL_GATE = REPO / "scripts" / "eval-gate.ps1"
SCOREBOARD = REPO / "eval" / "scoreboard.json"

def pwsh(args, cwd=None):
    return subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(EVAL_GATE)] + args,
        capture_output=True, text=True, timeout=30,
        cwd=str(cwd or REPO)
    )

def pwsh_ok():
    try:
        subprocess.run(["powershell", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False

def make_results(path, arm_b, tasks=9):
    lines = []
    for i in range(tasks):
        lines.append(json.dumps({"id":f"t{i}-A","task":f"t{i}","arm":"A_vanilla","rep":1,"f2p":1,"p2p":1,"resolved":1}))
        lines.append(json.dumps({"id":f"t{i}-B","task":f"t{i}","arm":"B_phoenix","rep":1,"f2p":1,"p2p":1,"resolved":1 if i<round(arm_b*tasks) else 0}))
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")

def gate_env(tmp_path, arm_b):
    (tmp_path/"scripts").mkdir(); (tmp_path/"eval").mkdir()
    shutil.copy(EVAL_GATE, tmp_path/"scripts"/"eval-gate.ps1")
    shutil.copy(REPO/"scripts"/"update-scoreboard.ps1", tmp_path/"scripts"/"update-scoreboard.ps1")
    shutil.copy(SCOREBOARD, tmp_path/"eval"/"scoreboard.json")
    (tmp_path/"README.md").write_text("# Test\n", encoding="utf-8")
    results = tmp_path/"prebuilt.jsonl"
    make_results(results, arm_b)
    return results

def test_eval_gate_exists():
    assert EVAL_GATE.exists()

def test_scoreboard_exists_for_gate():
    assert SCOREBOARD.exists(), "eval/scoreboard.json must exist for gate to run"

def test_exempt_flag_exits_0():
    if not pwsh_ok(): import pytest; pytest.skip("pwsh unavailable")
    r = pwsh(["-Exempt"])
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "EXEMPT" in r.stdout

def test_missing_scoreboard_exits_2(tmp_path):
    if not pwsh_ok(): import pytest; pytest.skip("pwsh unavailable")
    (tmp_path/"scripts").mkdir()
    shutil.copy(EVAL_GATE, tmp_path/"scripts"/"eval-gate.ps1")
    # no eval/scoreboard.json
    r = subprocess.run(["powershell","-ExecutionPolicy","Bypass","-File",
        str(tmp_path/"scripts"/"eval-gate.ps1")],
        capture_output=True, text=True, timeout=30, cwd=str(tmp_path))
    assert r.returncode == 2, f"{r.stdout}\n{r.stderr}"

def test_gate_passes_on_no_regression(tmp_path):
    if not pwsh_ok(): import pytest; pytest.skip("pwsh unavailable")
    results = gate_env(tmp_path, arm_b=1.0)
    r = subprocess.run(["powershell","-ExecutionPolicy","Bypass","-File",
        str(tmp_path/"scripts"/"eval-gate.ps1"),
        "-PrebuiltResults", str(results),
        "-ResultsOut", str(tmp_path/"out.jsonl")],
        capture_output=True, text=True, timeout=30, cwd=str(tmp_path))
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "PASS" in r.stdout

def test_gate_fails_on_regression(tmp_path):
    if not pwsh_ok(): import pytest; pytest.skip("pwsh unavailable")
    results = gate_env(tmp_path, arm_b=0.5)
    r = subprocess.run(["powershell","-ExecutionPolicy","Bypass","-File",
        str(tmp_path/"scripts"/"eval-gate.ps1"),
        "-PrebuiltResults", str(results),
        "-ResultsOut", str(tmp_path/"out.jsonl")],
        capture_output=True, text=True, timeout=30, cwd=str(tmp_path))
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
    assert "REGRESSION" in r.stdout or "REGRESSION" in r.stderr