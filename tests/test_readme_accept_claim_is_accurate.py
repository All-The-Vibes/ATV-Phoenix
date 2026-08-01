"""The README must not claim phoenix_accept does more than it does.

The core-loop table said phoenix_accept "rejects vacuous checks". It does not. It refuses any
check never observed failing, which is verifiable from the trace and true. It cannot detect a
test that asserts its own fixtures: PR #130 got a legitimate red to green because RED came from
the file not existing, and the gate had no way to tell.

Issue #146 makes the gap concrete. canonical_digest folds a script hash into check identity only
when target[0] is a file, so for ["python","-m","pytest","tests/x.py"] the test contents are not
part of the check at all. A guard can be weakened without changing its digest.

That is the whole reason this guard exists. The claim is the kind that quietly grows back.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"


def test_readme_does_not_overstate_what_accept_rejects():
    text = README.read_text(encoding="utf-8")
    assert "rejects vacuous checks" not in text, (
        "phoenix_accept refuses checks never observed failing. It cannot detect a test that "
        "asserts its own fixtures. See issue #139, issue #146, and the guard in "
        "tests/test_e2e_proof_is_not_vacuous.py."
    )
