"""#186 -- a fact has to earn its way into memory, and a scope change retires it.

`evals/arc/skills.py` stores a skill because a caller called `add`. Nothing about that is
checkable later, and nothing about it is reusable outside ARC. `phoenix_learn.memory` is the
domain-agnostic version with the two properties the ARC library does not have: the only way in
is `phoenix_learn.accept.verify_gate`, and a fact is keyed by scope so it can be retired.

These tests pin both, plus the audit trail that makes re-earning cheap after a scope change,
plus the file round trip that makes the store cross-episode at all.
"""
from __future__ import annotations

import json

import pytest

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


# ── cross-episode: the store has to outlive the process ──────────────────────────────
#
# The title of #186 is "no cross-episode memory primitive". An episode boundary in ARC is a
# process boundary: each run is a fresh interpreter that reads eval/arc-results/skills.json.
# A store held only in a dict is cross-SCOPE inside one process and forgets everything at
# exit, so it cannot be what `evals/arc/skills.py` becomes a view over. These pin the file
# round trip and, more importantly, that the gate is not something a file can walk past.


def test_a_fact_survives_a_round_trip_through_a_file(tmp_path):
    path = tmp_path / "memory.json"
    m = Memory(scope="level-1")
    m.remember("targets_on_row_29", [29], [Observation(False, seed=7, note="row 58 guess"), Observation(True, seed=7)])
    m.save(path)

    back = Memory.load(path)

    assert back.scope == "level-1", "the store must reopen in the scope it was saved in"
    assert back.recall("targets_on_row_29").value == [29]
    assert back.known() == ["targets_on_row_29"]

    ev = back.evidence("targets_on_row_29")
    assert ev["trials"] == [False, True], "the admitting evidence has to survive too"
    assert ev["verdict"]["ok"] is True
    assert ev["scope"] == "level-1"


def test_loading_re_runs_the_gate_so_an_edited_file_cannot_launder_a_fact(tmp_path):
    """The point of the module, restated for the one entrance a file opens.

    `remember` refuses a claim never seen failing. If `load` trusted what it read, writing
    that same claim into the JSON by hand would put it in the store anyway, and the gate
    would be a formality anyone with a text editor could skip.
    """
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "scope": "level-1",
                "facts": [
                    {
                        "key": "submit_is_action_5",
                        "value": True,
                        "scope": "level-1",
                        "trials": [{"ok": True}, {"ok": True}],
                        "verdict": {"ok": True, "reason": "trust me"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    back = Memory.load(path)

    assert back.recall("submit_is_action_5") is None
    assert back.known() == []
    assert back.evidence("submit_is_action_5") is None
    assert back.refused == ["submit_is_action_5"], "a refusal has to be reported, not silent"


def test_scope_retirement_survives_the_round_trip(tmp_path):
    path = tmp_path / "memory.json"
    m = Memory(scope="level-1")
    m.remember("targets_on_row_29", [29], RED_THEN_GREEN)
    m.enter("level-2")
    m.save(path)

    back = Memory.load(path)

    assert back.scope == "level-2"
    assert back.recall("targets_on_row_29") is None, "still not true in this scope after a reload"
    assert back.evidence("targets_on_row_29")["scope"] == "level-1", "and it still says where it was proved"


def test_loading_a_path_that_does_not_exist_is_an_empty_store(tmp_path):
    """First episode. There is no file yet and that is not an error."""
    back = Memory.load(tmp_path / "never-written.json", scope="level-1")

    assert back.known() == []
    assert back.scope == "level-1"
    assert back.refused == []


def test_saving_a_value_that_is_not_json_refuses_instead_of_writing_half_a_store(tmp_path):
    path = tmp_path / "memory.json"
    m = Memory(scope="level-1")
    m.remember("an_open_socket", object(), RED_THEN_GREEN)

    with pytest.raises(TypeError):
        m.save(path)
    assert not path.exists(), "a store that cannot be written must not leave a truncated file"
