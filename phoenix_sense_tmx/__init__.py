"""phoenix_sense_tmx — scope helper for C1 Verify x Context (issue #2).

For complete draft and exploration scopes, ``get_scope`` returns the union of
test files mapped to each changed symbol. All other decisions fail closed to
the full suite. Tests pass the graph directly so the decision logic is
independently verifiable without a live TMX instance.
"""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

FULL_SUITE_REQUIRED: Final = "full_suite_required"
ScopeMode: TypeAlias = Literal["draft", "exploration", "ship", "integration"]
ScopeDecision: TypeAlias = list[str] | Literal["full_suite_required"]


def get_scope(
    graph: dict[str, list[str]],
    changed_symbols: list[str],
    *,
    mode: ScopeMode = "draft",
) -> ScopeDecision:
    """Return a deterministic scoped test list, or require the full suite.

    Scoped lists are evidence for complete draft and exploration queries only.
    Missing graph coverage and ship or integration gates require the full suite.
    """
    if mode not in ("draft", "exploration") or not graph or not changed_symbols:
        return FULL_SUITE_REQUIRED

    scope: set[str] = set()
    for sym in changed_symbols:
        tests = graph.get(sym)
        if (
            not isinstance(tests, list)
            or not tests
            or any(not isinstance(test, str) or not test.strip() for test in tests)
        ):
            return FULL_SUITE_REQUIRED
        scope.update(tests)
    return sorted(scope)
