"""The swe-bench evidence stays retired, or this test says so.

The README presented the swe-bench-style result as a live row in its results table, and a
limitations bullet described the gate in the present tense as one that "has no headroom left" --
language about a gate still in use. The benchmark is out of scope for this project and the
measurement has not been refreshed since 2026-07-03, so presenting it as current evidence
overstates it.

Retiring a claim in prose is not durable on its own: the next person to edit the results table has
nothing telling them the row is historical, and a revert restores a current-tense claim about a
withdrawn benchmark without anyone noticing. This pins the retirement the same way
`test_okf_claim_discloses_its_limit.py` pins the OKF cost/quality disclosure.

Deliberately NOT asserted here: that the numbers are gone. They are not, and should not be. The
eval ran and the result is real; deleting it would be the dishonest option. What is asserted is
only that it is never presented as *current* evidence.

The detector carries its own unit tests. Without them this file would pass trivially if the
mentions were simply deleted, which is the outcome it exists to distinguish from retirement.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
HYPOTHESES = REPO_ROOT / "docs" / "intent-to-outcome.md"

# Words that mark a claim as historical rather than live.
RETIREMENT_MARKERS = ("retired", "withdrawn", "historical")


def mentions_swebench(line: str) -> bool:
    return "swe-bench" in line.lower() or "swe_bench" in line.lower()


def is_retired(line: str) -> bool:
    """True when a swe-bench line marks itself as no longer current evidence."""
    lowered = line.lower()
    return any(marker in lowered for marker in RETIREMENT_MARKERS)


def swebench_claim_lines(text: str) -> list[str]:
    """Table rows that cite the swe-bench result.

    Scoped to table rows on purpose. Prose that cites the swe-bench *discipline* -- confirm the
    check fails, fix, confirm it passes -- is the origin of Phoenix's failure-first gate, not a
    claim about our results, and must not be caught here.
    """
    return [
        line
        for line in text.splitlines()
        if line.lstrip().startswith("|") and mentions_swebench(line)
    ]


def test_detector_accepts_a_retired_row():
    row = "| [SWE-bench-style evaluation](x) - **retired, kept for the record** | 78% to 100% |"
    assert mentions_swebench(row) and is_retired(row)


def test_detector_rejects_a_live_row():
    row = "| [SWE-bench-style evaluation](x) | Overall resolved rate **78% to 100%** | 9 tasks |"
    assert mentions_swebench(row) and not is_retired(row)


def test_detector_ignores_prose_citing_the_methodology():
    prose = 'This is the SWE-bench discipline ("confirm it fails, fix, confirm it passes").'
    assert not swebench_claim_lines(prose), "a methodology citation is not a results claim"


def test_readme_never_presents_swebench_as_current_evidence():
    rows = swebench_claim_lines(README.read_text(encoding="utf-8"))
    assert rows, "the swe-bench row vanished; retirement keeps the record, it does not delete it"
    for row in rows:
        assert is_retired(row), (
            "README presents a swe-bench result as live evidence. The benchmark is out of scope "
            "and was last scored 2026-07-03; mark the row retired rather than restoring it as a "
            f"current claim:\n  {row.strip()}"
        )


def test_the_limitations_bullet_does_not_describe_a_live_gate():
    text = README.read_text(encoding="utf-8")
    stale = "- The swe-bench-style gate has no headroom left."
    assert stale not in text, (
        "the limitations bullet describes the swe-bench gate in the present tense as one that "
        "still runs; it is retired and gates nothing"
    )


def test_the_hypothesis_table_marks_swebench_retired():
    rows = swebench_claim_lines(HYPOTHESES.read_text(encoding="utf-8"))
    assert rows, "the swe-bench hypothesis row vanished; it should be retired, not deleted"
    for row in rows:
        assert is_retired(row), (
            f"docs/intent-to-outcome.md still reports swe-bench as standing evidence:\n  {row.strip()}"
        )
