"""
tests/test_harvest_datapoint.py
Acceptance tests for scripts/harvest-datapoint.ps1 (issues #38, #161).
Quality gates: valid harvest produces task dir; LAW 2 PII lint; saw_red gate;
blast-radius gate; red-before-fix gate; dogfood set accepted by run_swe.ps1.
"""
import errno
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
    """Report whether PowerShell can be invoked, and refuse to guess.

    The original form caught every exception and returned False, so a
    `subprocess.TimeoutExpired` from a loaded machine read as "PowerShell is not
    installed" and eleven tests in this file skipped themselves. The suite then exited 0.
    Observed on 2026-08-07: five identical runs on one machine produced 13 passed, 13
    passed, 8 passed with 5 skipped, 13 passed, 13 passed, with no code change between
    them. A green run that skipped its assertions is not evidence the assertions hold,
    which is the failure this file exists to catch in the harvester (issue #170).

    Only a genuine absence justifies a skip. A timeout is an environment failure and
    raises, so the run goes red and says why instead of quietly proving nothing.
    """
    try:
        subprocess.run(["powershell", "--version"], capture_output=True, timeout=30)
        return True
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return False
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "the PowerShell availability probe timed out after 30s. That is a loaded "
            "or broken environment, not a missing interpreter, and skipping here would "
            "report a pass for assertions that never ran."
        ) from exc


def _make_inputs(tmp_path, problem_text=None, f2p_text=None, p2p_text=None, solution_text=None, solution_name="solution.py"):
    """Create standard mock input files for the harvest script.

    The defaults are a genuine swe-bench-shaped task: `solution.py` carries a real bug,
    `test_f2p.py` fails against it, and `test_p2p.py` passes against it. Vacuous stubs here
    would make every caller of this helper prove nothing, which is what issue #161 found.
    """
    if problem_text is None:
        problem_text = "# Bug: clamp returns the lower bound when the value exceeds the upper bound\n\n`clamp(11, 0, 10)` should return 10."
    if solution_text is None:
        # Pre-fix state, exactly as run_swe.ps1 hands it to the agent.
        solution_text = (
            "def clamp(value, low, high):\n"
            '    """Clamp value into the inclusive range [low, high]."""\n'
            "    if value < low:\n"
            "        return low\n"
            "    if value > high:\n"
            "        return low  # BUG: should return high\n"
            "    return value\n"
        )
    if f2p_text is None:
        f2p_text = (
            "from solution import clamp\n\n\n"
            "def test_value_above_high_clamps_to_high():\n"
            "    assert clamp(11, 0, 10) == 10\n"
        )
    if p2p_text is None:
        p2p_text = (
            "from solution import clamp\n\n\n"
            "def test_lower_bound_and_passthrough_unchanged():\n"
            "    assert clamp(-5, 0, 10) == 0\n"
            "    assert clamp(5, 0, 10) == 5\n"
        )
    problem = tmp_path / "problem.md"
    problem.write_text(problem_text, encoding="utf-8")
    solution = tmp_path / solution_name
    solution.write_text(solution_text, encoding="utf-8")
    test_f2p = tmp_path / "test_f2p.py"
    test_f2p.write_text(f2p_text, encoding="utf-8")
    test_p2p = tmp_path / "test_p2p.py"
    test_p2p.write_text(p2p_text, encoding="utf-8")
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


def test_red_before_fix_rejects_vacuous_f2p(tmp_path):
    """An f2p that passes against the pre-fix solution scores resolved with no fix applied."""
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(
        tmp_path, f2p_text="def test_fix_passes(): assert True\n")
    proof = _make_proof(tmp_path)
    r, out_dir = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode != 0, f"Expected non-zero exit for an f2p that already passes\n{r.stdout}"
    assert "RED_BEFORE_FIX" in r.stdout, r.stdout
    assert not (out_dir / "99-test-issue").exists(), "Rejected task must not be written to disk"


def test_red_before_fix_rejects_p2p_that_cannot_pass(tmp_path):
    """A p2p that fails pre-fix can never pass, so the task can never score resolved."""
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(
        tmp_path, p2p_text="from solution import nonexistent_symbol\n\n\ndef test_regression(): assert True\n")
    proof = _make_proof(tmp_path)
    r, out_dir = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode != 0, f"Expected non-zero exit for a p2p that cannot pass\n{r.stdout}"
    assert "RED_BEFORE_FIX" in r.stdout, r.stdout
    assert not (out_dir / "99-test-issue").exists(), "Rejected task must not be written to disk"


def test_red_before_fix_rejects_unscoreable_language(tmp_path):
    """run_swe.ps1 scores every task with pytest, so a non-Python solution can never resolve."""
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(
        tmp_path, solution_text="pub fn clamp() {}\n", solution_name="solution.rs")
    proof = _make_proof(tmp_path)
    r, _ = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode != 0, f"Expected non-zero exit for a solution pytest cannot import\n{r.stdout}"
    assert "RED_BEFORE_FIX" in r.stdout, r.stdout


def test_red_before_fix_accepts_a_genuine_task(tmp_path):
    """The gate must not reject a real fail-to-pass task. Guards against a gate that rejects everything."""
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(tmp_path)
    proof = _make_proof(tmp_path)
    r, out_dir = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode == 0, f"Genuine task was rejected\n{r.stdout}\n{r.stderr}"
    assert (out_dir / "99-test-issue" / "solution.py").exists()


def test_red_before_fix_emitted_task_is_executable(tmp_path):
    """Independent read-back: replay run_swe.ps1's Score contract on the emitted task directory.

    Pre-fix the emitted task must be f2p-red and p2p-green. Applying the documented fix must turn
    f2p green with p2p still green. That is the SWE-bench resolved contract, verified end to end.
    """
    if not _pwsh_available():
        import pytest; pytest.skip("PowerShell not available")
    problem, solution, test_f2p, test_p2p = _make_inputs(tmp_path)
    proof = _make_proof(tmp_path)
    r, out_dir = _run_harvest(tmp_path, problem, solution, test_f2p, test_p2p, proof)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    task_dir = out_dir / "99-test-issue"

    scratch = tmp_path / "score"
    scratch.mkdir()
    for name in ("solution.py", "test_f2p.py", "test_p2p.py"):
        shutil.copy(task_dir / name, scratch / name)

    def _pytest(target):
        return subprocess.run(
            ["python", "-m", "pytest", target, "-q"],
            cwd=str(scratch), capture_output=True, text=True, timeout=120).returncode

    assert _pytest("test_f2p.py") != 0, "Emitted task is vacuous: f2p passes before any fix"
    assert _pytest("test_p2p.py") == 0, "Emitted task is unscoreable: p2p fails before any fix"

    fixed = (scratch / "solution.py").read_text(encoding="utf-8").replace(
        "return low  # BUG: should return high", "return high")
    (scratch / "solution.py").write_text(fixed, encoding="utf-8")

    assert _pytest("test_f2p.py") == 0, "f2p still fails after the documented fix"
    assert _pytest("test_p2p.py") == 0, "fix regressed p2p"


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


# --- issue #170: the availability probe must not turn an environment failure into a skip ---


def test_probe_returns_false_when_powershell_is_genuinely_absent(monkeypatch):
    """A missing interpreter is the one condition that justifies skipping."""
    def _absent(*args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(subprocess, "run", _absent)
    assert _pwsh_available() is False


def test_probe_raises_when_the_probe_times_out(monkeypatch):
    """A timeout is a loaded machine, not a missing interpreter.

    This is the whole bug. The old probe caught TimeoutExpired and returned False, so
    eleven tests skipped and the suite exited 0.
    """
    def _slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["powershell", "--version"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _slow)
    import pytest

    with pytest.raises(RuntimeError) as caught:
        _pwsh_available()
    assert "timed out" in str(caught.value)


def test_probe_does_not_swallow_unexpected_errors(monkeypatch):
    """Anything that is neither absence nor timeout must surface, not read as absent."""
    def _broken(*args, **kwargs):
        raise OSError(errno.E2BIG, "argument list too long")

    monkeypatch.setattr(subprocess, "run", _broken)
    import pytest

    with pytest.raises(OSError):
        _pwsh_available()


def test_probe_reports_true_on_a_machine_with_powershell():
    """Guards this file against the false-skip state returning silently.

    If PowerShell is present and the probe still says otherwise, every skip below is a
    lie, so this fails rather than letting eleven tests vanish.
    """
    if shutil.which("powershell") is None:
        import pytest

        pytest.skip("PowerShell is genuinely absent on this machine")
    assert _pwsh_available() is True
