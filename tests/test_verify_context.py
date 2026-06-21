"""Acceptance check for C1 — Verify x Context: TMX-scoped phoenix_sense (issue #2).

The gate: phoenix_sense called for a changed symbol X should run EXACTLY the
tests in the TMX impact set for X — no more, no less.  This starts RED
(phoenix_sense_tmx does not exist) and goes GREEN once `get_scope` is
implemented.

Done-check: `pytest tests/test_verify_context.py` exits 0.
The TMX MCP integration (fetching the live graph from TokenMaster) is a
future beat; this beat pins the interface and decision logic with a
deterministic fixture graph, proving the core scoping contract.
"""

# ---- fixture: a minimal symbol -> test-file graph --------------------------
FIXTURE_GRAPH = {
    "parse_args": ["tests/test_cli.py", "tests/test_parse.py"],
    "read_file":  ["tests/test_cli.py", "tests/test_file_ops.py"],
    "run_gate":   ["tests/test_gate.py"],
}

FIXTURE_ALL_TESTS = [
    "tests/test_cli.py",
    "tests/test_parse.py",
    "tests/test_file_ops.py",
    "tests/test_gate.py",
    "tests/test_unrelated.py",   # NOT in any symbol impact set
]


def test_impact_set_exact_match_single_symbol():
    """Gate selects exactly the graph-derived tests for a single changed symbol."""
    from phoenix_sense_tmx import get_scope

    scope = get_scope(FIXTURE_GRAPH, changed_symbols=["parse_args"])
    expected = {"tests/test_cli.py", "tests/test_parse.py"}
    assert set(scope) == expected, f"Expected {expected}, got {set(scope)}"


def test_impact_set_excludes_unrelated_test():
    """A test not in any impact set for the changed symbol MUST NOT be selected."""
    from phoenix_sense_tmx import get_scope

    scope = get_scope(FIXTURE_GRAPH, changed_symbols=["run_gate"])
    assert "tests/test_unrelated.py" not in scope, (
        "test_unrelated.py should not be selected — outside run_gate impact set"
    )


def test_impact_set_union_for_multiple_symbols():
    """Multiple changed symbols -> scope is the UNION of their impact sets."""
    from phoenix_sense_tmx import get_scope

    scope = get_scope(FIXTURE_GRAPH, changed_symbols=["parse_args", "run_gate"])
    expected = {"tests/test_cli.py", "tests/test_parse.py", "tests/test_gate.py"}
    assert set(scope) == expected, f"Expected {expected}, got {set(scope)}"


def test_unknown_symbol_returns_empty_scope():
    """A symbol with no graph entry returns empty scope, NOT the full suite."""
    from phoenix_sense_tmx import get_scope

    scope = get_scope(FIXTURE_GRAPH, changed_symbols=["nonexistent_symbol"])
    assert scope == [], f"Unknown symbol should yield [], got {scope}"


def test_full_suite_not_returned_for_partial_change():
    """Regression guard: scoped run is strictly smaller than the full test suite."""
    from phoenix_sense_tmx import get_scope

    scope = get_scope(FIXTURE_GRAPH, changed_symbols=["run_gate"])
    # run_gate only touches test_gate.py; all others must be excluded
    for test_file in FIXTURE_ALL_TESTS:
        if test_file not in ["tests/test_gate.py"]:
            assert test_file not in scope, (
                f"{test_file} must be excluded when only run_gate changed"
            )
