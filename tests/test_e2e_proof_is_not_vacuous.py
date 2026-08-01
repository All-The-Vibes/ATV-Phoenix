"""Guard against an end-to-end proof that does not execute anything.

PR #130 merged tests/test_hybrid_mission_e2e.py, which closed issue #86 while running no part
of Phoenix. It appended Event(INTEGRATION_COMPLETED, ok=True) and then asserted that event was
present. It collected a valid failure-first trace anyway, because RED came from the file not
existing yet rather than from the property being false.

Vacuity is invisible to a command_exit gate: a test asserting 8 > 7 exits 0 exactly like a real
one. So the check has to read the source.

The detector below carries its own unit tests. Without them this file would pass trivially
whenever no end-to-end proof exists on disk, which is the same shape it exists to reject.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_PROOF = REPO_ROOT / "tests" / "test_hybrid_mission_e2e.py"

# A proof has to reach the system under test through one of these.
EXECUTION_MARKERS = ("subprocess", "CARGO_BIN_EXE", "Popen", "check_output")

# And it has to consult Phoenix evidence rather than objects it built itself.
EVIDENCE_MARKERS = ("verify_trace", "verify-trace", "phoenix-mcp accept", "phoenix_accept")


def touches_real_system(source: str) -> bool:
    """True when source both executes something and reads Phoenix evidence back."""
    executes = any(marker in source for marker in EXECUTION_MARKERS)
    reads_evidence = any(marker in source for marker in EVIDENCE_MARKERS)
    return executes and reads_evidence


VACUOUS_SAMPLE = "\n".join([
    "def test_hybrid_mission_end_to_end_proof():",
    "    ready = {\"A\", \"B\"}",
    "    assert ready == {\"A\", \"B\"}",
    "    pre, post = 7, 8",
    "    assert post > pre",
    "    projected = []",
    "    projected.append(Event(kind=EventKind.INTEGRATION_COMPLETED, ok=True))",
    "    assert projected[-1].ok is True",
])

REAL_SAMPLE = "\n".join([
    "import subprocess",
    "def test_hybrid_mission_end_to_end_proof(tmp_path):",
    "    subprocess.run([BIN, \"--workspace\", str(tmp_path)], check=True)",
    "    report = json.loads(run([MCP, \"verify_trace\"]).stdout)",
    "    assert report[\"ok\"] and report[\"broken_at\"] is None",
])


def test_detector_rejects_a_proof_that_only_asserts_its_own_fixtures():
    assert not touches_real_system(VACUOUS_SAMPLE)


def test_detector_accepts_a_proof_that_runs_the_binary_and_reads_the_trace():
    assert touches_real_system(REAL_SAMPLE)


def test_detector_requires_both_halves_not_just_one():
    executes_only = "import subprocess\nsubprocess.run([BIN])"
    evidence_word_only = "# we should call verify_trace one day"
    assert not touches_real_system(executes_only)
    assert not touches_real_system(evidence_word_only)


def test_any_hybrid_mission_e2e_proof_on_disk_executes_phoenix():
    if not E2E_PROOF.exists():
        return
    source = E2E_PROOF.read_text(encoding="utf-8")
    assert touches_real_system(source), (
        f"{E2E_PROOF.name} claims to prove the hybrid mission but does not execute anything. "
        "It must run the binary or phoenix-mcp and assert on the trace, not on objects it "
        "constructed itself. See issue #139."
    )
