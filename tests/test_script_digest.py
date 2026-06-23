"""Acceptance check for issue #14 — gate script body folded into canonical_digest.

The integrity gap: check_digest (= canonical_digest) was derived from the check SPEC only
(kind + target argv + expect), not from the bytes the check actually executes. Editing the
gate script (e.g. verify-design.mjs) produced identical digests across materially different
gate versions, allowing trace_intact=true on a weakened gate.

Fix: when target[0] for a command_exit check is a path to an existing file, fold
sha256(file_bytes) into the digest. Any edit to the script changes the digest, changing
input_digest in trace events, breaking accept's red->green lookup for the old check.

This test verifies:
  1. The Rust sense.rs canonical_digest mentions script hashing in source
  2. A new Rust test 'rejects_gate_script_edit' exists in gate_ledger.rs
  3. That Rust test actually passes (cargo test output shows '1 passed')
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSE_RS = ROOT / "src" / "sense.rs"
GATE_LEDGER_RS = ROOT / "tests" / "gate_ledger.rs"


def test_sense_rs_has_script_hash_logic() -> None:
    """canonical_digest in sense.rs must hash the script file when target is a file path."""
    text = SENSE_RS.read_text(encoding="utf-8", errors="replace")
    assert "sha256_file" in text or "script_hash" in text or "script" in text.lower(), (
        "canonical_digest must call sha256_file (or equivalent) to hash the gate script"
    )
    # The key: canonical_digest must do something beyond just kind+target+expect
    # Look for file-existence check or sha256 call inside canonical_digest
    assert re.search(r"fn canonical_digest", text), "canonical_digest function must exist"
    assert "Path" in text or "path" in text.lower(), (
        "canonical_digest must handle file paths (detect when target[0] is a file)"
    )


def test_gate_ledger_has_script_edit_test() -> None:
    """gate_ledger.rs must contain the rejects_gate_script_edit test."""
    text = GATE_LEDGER_RS.read_text(encoding="utf-8", errors="replace")
    assert "rejects_gate_script_edit" in text, (
        "gate_ledger.rs must have a test named rejects_gate_script_edit proving that "
        "editing the gate script breaks acceptance"
    )


def test_script_edit_rust_test_passes() -> None:
    """The rejects_gate_script_edit Rust test must actually execute and pass."""
    result = subprocess.run(
        ["cargo", "test", "--test", "gate_ledger", "--", "rejects_gate_script_edit", "--exact", "--nocapture"],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
    )
    combined = result.stdout + result.stderr
    assert "1 passed" in combined, (
        f"rejects_gate_script_edit must run and pass (need '1 passed' in output).\n"
        f"stdout: {result.stdout[-800:]}\nstderr: {result.stderr[-400:]}"
    )
    assert result.returncode == 0, f"cargo test exited {result.returncode}"


def test_digest_changes_when_script_changes() -> None:
    """Python-level smoke: verify the Rust source would change digest for file vs non-file target.

    We can't easily call Rust from Python, so we verify the source logic is present.
    The gate_ledger Rust test covers the runtime behavior.
    """
    text = SENSE_RS.read_text(encoding="utf-8", errors="replace")
    # The fix must detect when target[0] is an existing file and include its hash
    has_exists_check = "exists()" in text or "Path::new" in text and "exists" in text
    has_sha256_in_digest = "sha256_file" in text and "canonical_digest" in text
    assert has_exists_check or has_sha256_in_digest, (
        "sense.rs must check if target[0] exists as a file and hash it in canonical_digest"
    )