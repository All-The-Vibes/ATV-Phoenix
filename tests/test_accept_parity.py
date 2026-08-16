"""#182 -- the failure-first rule exists in Rust and in Python, so pin them to one fixture.

`src/accept.rs::verify_gate` owns the rule for MCP callers. `phoenix_learn.accept.verify_gate`
owns it for Python callers, because a Python process cannot reach the Rust one. Before this
file existed, `evals/arc/phoenix_loop.py` carried a third copy that required `green >= 2`, so
the same evidence was accepted over MCP and refused in-process. That copy is gone and both
`phoenix_learn/accept.py` and `evals/arc/phoenix_loop.py` claim in their docstrings that this
test pins the two remaining ones together. Until now the file they named did not exist.

`tests/accept_parity_cases.json` is the contract. This test runs every case through the Python
gate. `tests/accept_parity.rs` runs the same cases through the Rust gate. A rule change made on
one side and not the other fails one of them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from phoenix_learn.accept import verify_gate

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "accept_parity_cases.json"
RUST_TEST = HERE / "accept_parity.rs"

FIELDS = ("saw_red", "green_after_red", "currently_green", "ok")


def _cases():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_python_gate_matches_the_shared_contract(case):
    got = verify_gate(case["trials"])
    for field in FIELDS:
        assert got[field] == case[field], (
            f"{case['name']}: python verify_gate returned {field}={got[field]!r}, "
            f"the shared contract says {case[field]!r}. Either the Python rule drifted or "
            f"tests/accept_parity_cases.json is wrong; whichever it is, src/accept.rs and "
            f"phoenix_learn/accept.py no longer agree."
        )


def test_the_rust_side_reads_the_same_fixture():
    """A fixture only one language reads is not a parity contract.

    This does not run the Rust gate. `cargo test --test accept_parity` does, and
    `scripts/ci-local.sh` stage 1 runs `cargo test --locked`. What this asserts is that the
    Rust test still points at THIS file, so the two suites cannot quietly diverge onto
    separate fixtures.
    """
    assert RUST_TEST.exists(), "tests/accept_parity.rs is missing, so nothing pins the Rust gate"
    source = RUST_TEST.read_text(encoding="utf-8")
    assert FIXTURE.name in source, (
        f"tests/accept_parity.rs no longer names {FIXTURE.name}, so the two suites are reading "
        "different contracts and parity is unenforced"
    )


def test_one_green_after_one_red_is_enough():
    """The exact drift #182 recorded, pinned on its own.

    The deleted `phoenix_loop.py` copy required two greens. That single extra condition is
    what made "proven" mean two different things in one repo, and it is invisible in any case
    that happens to have two greens in it.
    """
    assert verify_gate([False, True])["ok"] is True
