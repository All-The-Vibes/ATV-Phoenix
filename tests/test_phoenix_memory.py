"""#186 -- a fact has to earn its way into memory, and a scope change retires it.

`evals/arc/skills.py` stores a skill because a caller called `add`. Nothing about that is
checkable later, and nothing about it is reusable outside ARC. `phoenix_learn.memory` is the
domain-agnostic version with the two properties the ARC library does not have: the only way in
is `phoenix_learn.accept.verify_gate`, and a fact is keyed by scope so it can be retired.

These tests pin both, plus the audit trail that makes re-earning cheap after a scope change.
"""
from __future__ import annotations

from phoenix_learn.accept import Observation
from phoenix_learn.memory import Fact, Memory

RED_THEN_GREEN = [False, True]


def test_a_claim_never_seen_failing_is_refused():
    """Assertion is not evidence. This is the whole point of the module."""
    m = Memory(scope="level-1")
    out = m.remember("submit_is_action_5", True, [True, True, True])

    assert out["stored"] is False
    assert out["fact"] is None
    assert out["saw_red"] is False
    assert m.recall("submit_is_action_5") is None
    assert m.known() == []


def test_no_trials_at_all_is_refused():
    m = Memory(scope="level-1")
    out = m.remember("nothing_backs_this", 1, [])

    assert out["stored"] is False
    assert m.known() == []


def test_a_claim_still_red_is_refused():
    """Seen failing and not yet fixed is not a fact either."""
    m = Memory(scope="level-1")
    out = m.remember("half_done", 1, [False, True, False])

    assert out["stored"] is False
    assert out["green_after_red"] is True
    assert out["currently_green"] is False
    assert m.known() == []


def test_one_red_then_one_green_is_enough_to_store():
    m = Memory(scope="level-1")
    out = m.remember("targets_on_row_29", [29], RED_THEN_GREEN)

    assert out["stored"] is True
    assert isinstance(out["fact"], Fact)
    assert m.recall("targets_on_row_29").value == [29]
    assert m.known() == ["targets_on_row_29"]


def test_the_admitting_evidence_is_kept_with_the_fact():
    m = Memory(scope="level-1")
    m.remember("targets_on_row_29", [29], [Observation(False, note="row 58 guess"), Observation(True)])

    ev = m.evidence("targets_on_row_29")
    assert ev["trials"] == [False, True]
    assert ev["verdict"]["ok"] is True
    assert ev["scope"] == "level-1"


def test_entering_a_new_scope_retires_what_was_earned_in_the_old_one():
    """#181 measured the cost of not doing this: level-1 geometry applied to level 2."""
    m = Memory(scope="level-1")
    m.remember("targets_on_row_29", [29], RED_THEN_GREEN)

    dropped = m.enter("level-2")

    assert dropped == ["targets_on_row_29"]
    assert m.recall("targets_on_row_29") is None
    assert m.known() == []


def test_a_retired_fact_keeps_its_evidence_so_re_earning_is_cheap():
    m = Memory(scope="level-1")
    m.remember("targets_on_row_29", [29], RED_THEN_GREEN)
    m.enter("level-2")

    assert m.recall("targets_on_row_29") is None, "it is not true here until re-earned"
    ev = m.evidence("targets_on_row_29")
    assert ev is not None, "the evidence that first proved it must survive the retirement"
    assert ev["scope"] == "level-1", "and it must say which world it was proved in"


def test_re_entering_the_same_scope_drops_nothing():
    m = Memory(scope="level-1")
    m.remember("targets_on_row_29", [29], RED_THEN_GREEN)

    assert m.enter("level-1") == []
    assert m.known() == ["targets_on_row_29"]


def test_the_store_is_domain_agnostic():
    """Nothing here knows what an ARC level is. A shell agent stores the same shape."""
    m = Memory(scope="host:build-box")
    m.remember("rm_needs_rf_for_dirs", "rm -rf", RED_THEN_GREEN)
    m.remember("tar_x_infers_compression", True, [False, True, False, True])

    assert m.known() == ["rm_needs_rf_for_dirs", "tar_x_infers_compression"]
    assert m.recall("rm_needs_rf_for_dirs").value == "rm -rf"


def test_summary_names_the_scope_and_says_nothing_when_empty():
    m = Memory(scope="level-1")
    assert "nothing earned in this scope" in m.summary()

    m.remember("targets_on_row_29", [29], RED_THEN_GREEN)
    text = m.summary()
    assert "level-1" in text
    assert "targets_on_row_29" in text
