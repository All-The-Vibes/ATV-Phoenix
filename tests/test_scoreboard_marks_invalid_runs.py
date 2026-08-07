"""
tests/test_scoreboard_marks_invalid_runs.py

Guard for issue #147: eval/scoreboard.json had no way to say "this measurement
is void". The baseline.north_star block recorded a run that was broken and never
published, and nothing in the file distinguished it from a real result. An agent
read it as evidence and wrote it into the README before the premise was corrected.

The fix is a validity marker, not a deletion, so the numbers stay readable and
their status is readable with them.

The last test here is the one that stops the guard being gamed. A test that only
checks "north_star is void" is satisfied by marking the whole file void, which
would destroy the evidence table instead of correcting it.
"""
import json
import pathlib

REPO = pathlib.Path(__file__).parent.parent
SCOREBOARD = REPO / "eval" / "scoreboard.json"


def _board():
    return json.loads(SCOREBOARD.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8"))


def _result_blocks(board):
    """Blocks under baseline are the dict-valued entries. date and commit are scalars."""
    return {k: v for k, v in board["baseline"].items() if isinstance(v, dict)}


def test_every_baseline_block_declares_validity():
    blocks = _result_blocks(_board())
    assert blocks, "baseline carries no result blocks"
    missing = [name for name, block in blocks.items() if not isinstance(block.get("valid"), bool)]
    assert not missing, f"baseline blocks with no explicit valid boolean: {missing}"


def test_north_star_is_marked_void_with_a_reason():
    ns = _board()["baseline"]["north_star"]
    assert ns["valid"] is False, "the 2026-07-03 north_star run was broken and never published"
    reason = ns.get("invalidated_reason", "")
    assert isinstance(reason, str) and reason.strip(), "valid: false needs invalidated_reason"


def test_any_void_block_carries_a_reason():
    for name, block in _result_blocks(_board()).items():
        if block.get("valid") is False:
            reason = block.get("invalidated_reason", "")
            assert isinstance(reason, str) and reason.strip(), (
                f"baseline.{name} is void with no invalidated_reason"
            )


def test_swe_bench_lite_stays_valid():
    """Marking the whole file void would satisfy the tests above. It must not satisfy this one."""
    lite = _board()["baseline"]["swe_bench_lite"]
    assert lite["valid"] is True, "swe_bench_lite is a real result and must stay admissible"
    assert "invalidated_reason" not in lite, "a valid block must not carry an invalidation reason"
