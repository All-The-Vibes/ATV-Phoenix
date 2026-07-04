"""
tests/test_harvest_datapoint.py
Acceptance tests for scripts/harvest-datapoint.ps1 (issue #38).
Quality gates: valid harvest produces task dir; LAW 2 PII lint; saw_red gate;
blast-radius gate; dogfood set accepted by run_swe.ps1.
"""
import json
import os
import pathlib
import subprocess
import shutil
import tempfile

REPO = pathlib.Path(__file__).parent.parent
HARVEST_SCRIPT = REPO / "scripts" / "harvest-datapoint.ps1"
RUN_SWE = REPO / "evals" / "swe-bench-lite" / "run_swe.ps1"


def _pwsh_available():
    try:
        subprocess.run(["powershell", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _make_inputs(tmp_path, problem_text=None):
    """Create standard mock input files for the harvest script."""
    if problem_text is None:
        problem_text = "# Bug: off-by-one in cache eviction\n\nThe LRU eviction policy fails under concurrent access."
    problem = tmp_path / "problem.md"
    problem.write_text(problem_text, encoding="utf-8")
    solution = tmp_path / "solution.py"
    solution.write_text("def broken(): return None  # pre-patch stub\n", encoding="utf-8")
    test_f2p = tmp_path / "test_f2p.py"
    test_f2p.write_text("def test_fix_passes(): assert True\n", encoding="utf-8")
    test_p2p = tmp_path / "test_p2p.py"
    test_p2p.write_text("def test_regression(): assert True\n", encoding="utf-8")
    return problem, solution, test_f2p, test_p2p


def _make_proof(tmp_path, saw_red=True, green_after_red=True, trace_intact=True, digest="deadbeef"):
    proof = tmp_path / "proof.json"
    proof.write_text(json.dumps({
        "ok": saw_red and green_after_red and trace_intact,
        "check_digest": digest,
        "saw_red": saw_red,
        "green_after_red": green_after_red,
        "trace_intact": trace_intact,
        "currently_green": True,
        "reason": "test-mock"
    }), encoding="utf-8")
    return proof


def _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof, changed_files="src/lib.rs,tests/test.rs", issue="99", slug="test-issue", out_dir=None):
    if out_dir is None:
        out_dir = tmp_path / "out"
        out_dir.mkdir(exist_ok=True)
    return subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(HARVEST_SCRIPT),
         "-IssueNumber", issue,
         "-IssueSlug", slug,
         "-ProblemFile", str(problem),
         "-SolutionFile", str(solution),
         "-TestF2PFile", str(test_f2p),
         "-TestP2PFile", str(test_p2p),
         "-AcceptProofFile", str(proof),
         "-ChangedFiles", changed_files,
         "-OutDir", str(out_dir)],
        capture_output=True, text=True, timeout=30
    ), out_dir


def test_harvest_script_exists():
    assert HARVEST_SCRIPT.exists(), f"Missing: {HARVEST_SCRIPT}"


def test_harvest_produces_valid_task_dir(tmp_path):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(tmp_path)
    proof = _make_proof(tmp_path)
    r, out_dir = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode == 0, f"Expected exit 0, got {r.returncode}\n{r.stdout}\n{r.stderr}"
    task_dir = out_dir / "99-test-issue"
    assert (task_dir / "problem.md").exists(), "problem.md missing"
    assert (task_dir / "solution.py").exists(), "solution.py missing"
    assert (task_dir / "test_f2p.py").exists(), "test_f2p.py missing"
    assert (task_dir / "test_p2p.py").exists(), "test_p2p.py missing"
    assert (task_dir / "meta.json").exists(), "meta.json missing"


def test_meta_json_schema(tmp_path):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(tmp_path)
    proof = _make_proof(tmp_path, digest="abc123digest")
    r, out_dir = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    meta = json.loads((out_dir / "99-test-issue" / "meta.json").read_text(encoding="utf-8"))
    assert meta["issue_number"] == "99"
    assert meta["issue_slug"] == "test-issue"
    assert meta["trace_digest"] == "abc123digest"
    assert meta["saw_red"] is True
    assert "harvested_at" in meta


def test_pii_lint_rejects_email(tmp_path):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(
        tmp_path, problem_text="Contact developer@example.com for details.")
    proof = _make_proof(tmp_path)
    r, _ = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode != 0, "Expected non-zero exit for email in problem.md"
    assert "LAW2_PII" in r.stdout or "email" in r.stdout.lower()


def test_pii_lint_rejects_handle(tmp_path):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(
        tmp_path, problem_text="Reported by @johndoe123 in the issue tracker.")
    proof = _make_proof(tmp_path)
    r, _ = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode != 0, "Expected non-zero exit for @handle in problem.md"
    assert "LAW2_PII" in r.stdout or "handle" in r.stdout.lower()


def test_quality_gate_rejects_saw_red_false(tmp_path):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(tmp_path)
    proof = _make_proof(tmp_path, saw_red=False)
    r, _ = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode != 0, "Expected non-zero exit for saw_red=false"
    assert "saw_red" in r.stdout.lower() or "GATE_FAIL" in r.stdout


def test_quality_gate_rejects_large_patch(tmp_path):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(tmp_path)
    proof = _make_proof(tmp_path)
    # 4 files — exceeds blast-radius budget
    four_files = "src/a.rs,src/b.rs,src/c.rs,tests/d.rs"
    r, _ = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof, changed_files=four_files)
    assert r.returncode != 0, "Expected non-zero exit for blast_radius > 3"
    assert "blast_radius" in r.stdout or "GATE_FAIL" in r.stdout


def test_dogfood_set_accepted_by_run_swe(tmp_path):
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    assert RUN_SWE.exists(), f"run_swe.ps1 not found: {RUN_SWE}"
    # run_swe.ps1 with -Set dogfood on an empty/nonexistent dogfood dir should exit without crashing
    dogfood_tasks = tmp_path / "tasks"  # empty, no tasks
    dogfood_tasks.mkdir()
    r = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(RUN_SWE),
         "-Set", "dogfood",
         "-TasksDir", str(dogfood_tasks),
         "-OutFile", str(tmp_path / "results.jsonl"),
         "-Filter", "no-match-*"],
        capture_output=True, text=True, timeout=60
    )
    # Should exit 0 (no tasks is a valid no-op run), not crash
    assert r.returncode == 0, f"run_swe.ps1 -Set dogfood exited {r.returncode}\n{r.stdout}\n{r.stderr}"
