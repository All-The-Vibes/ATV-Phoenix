"""phoenix_sense_tmx — scope helper for C1 Verify x Context (issue #2).

get_scope(graph, changed_symbols) returns the UNION of test files mapped to
each changed symbol in the code graph.  In production the graph is fetched
from the TokenMasterX MCP server; tests pass the graph directly so the
decision logic is independently verifiable without a live TMX instance.
"""

from __future__ import annotations

from typing import Dict, List


def get_scope(graph: Dict[str, List[str]], changed_symbols: List[str]) -> List[str]:
    """Return the sorted, deduplicated list of test files that cover the
    changed symbols, derived from *graph*.

    Rules enforced here (and checked by tests/test_verify_context.py):
    - Scope = UNION of graph[sym] for each sym in changed_symbols.
    - A symbol absent from the graph contributes nothing (empty, not full suite).
    - A test file NOT in any impacted symbol's set is excluded.
    - Result is deterministic (sorted) so callers can assert equality by value.
    """
    scope: set[str] = set()
    for sym in changed_symbols:
        scope.update(graph.get(sym, []))
    return sorted(scope)
