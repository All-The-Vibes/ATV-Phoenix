"""Acceptance tests for the derived event projection (#83).

The projection is *derived*, never canonical. These tests pin the two consequences of that: it can
be regenerated from evidence without loss, and a damaged projection is reported rather than read as
merely smaller.
"""

from __future__ import annotations

import json

import pytest

from phoenix_learn.events import (
    Event,
    EventKind,
    Projection,
    derive_from_ledger,
    read_projection,
    write_projection,
)


def _ledger_row(goal, backend="copilot_cloud", error=None, i=None, o=None, cost=None):
    return {
        "goal": goal,
        "backend": backend,
        "error": error,
        "input_tokens": i,
        "output_tokens": o,
        "cost_micros": cost,
    }


def test_event_round_trips_through_json():
    e = Event(
        kind=EventKind.GOAL_FINISHED,
        mission="m1",
        goal="g1",
        ok=True,
        backend="local",
        tokens=150,
        cost_micros=2500,
    )
    assert Event.from_json(e.to_json()) == e


def test_absent_fields_are_omitted_not_nulled():
    e = Event(kind=EventKind.MISSION_STARTED, mission="m1")
    d = json.loads(e.to_json())

    assert "goal" not in d, "an absent field must not serialise as an explicit null"
    assert "ok" not in d
    assert d["kind"] == "mission_started"


def test_ok_is_tristate():
    started = Event(kind=EventKind.MISSION_STARTED, mission="m1")
    failed = Event(kind=EventKind.GOAL_FINISHED, mission="m1", goal="g", ok=False)

    assert started.ok is None, "an event with no pass/fail semantics is not a failure"
    assert failed.ok is False
    assert started.ok is not failed.ok


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        Event.from_json(json.dumps({"kind": "invented_kind", "mission": "m1"}))


def test_ledger_rows_derive_backend_and_outcome_events():
    events = derive_from_ledger("m1", [_ledger_row("g1", i=100, o=50, cost=2000)])

    kinds = [e.kind for e in events]
    assert EventKind.BACKEND_SELECTED in kinds
    assert EventKind.GOAL_FINISHED in kinds

    finished = next(e for e in events if e.kind is EventKind.GOAL_FINISHED)
    assert finished.ok is True
    assert finished.tokens == 150
    assert finished.cost_micros == 2000


def test_a_failed_row_derives_a_failed_goal_carrying_its_reason():
    events = derive_from_ledger("m1", [_ledger_row("g1", error="runner out of quota")])
    finished = next(e for e in events if e.kind is EventKind.GOAL_FINISHED)

    assert finished.ok is False
    assert finished.detail == "runner out of quota"


def test_a_failed_row_still_derives_a_backend_selection():
    events = derive_from_ledger("m1", [_ledger_row("g1", backend="copilot_cloud", error="boom")])
    selected = next(e for e in events if e.kind is EventKind.BACKEND_SELECTED)

    assert selected.backend == "copilot_cloud", (
        "'we chose cloud and it failed' is a fact worth counting"
    )


def test_half_known_tokens_do_not_produce_a_total():
    events = derive_from_ledger("m1", [_ledger_row("g1", i=100, o=None)])
    finished = next(e for e in events if e.kind is EventKind.GOAL_FINISHED)

    assert finished.tokens is None, "a total from one half would be an invented number"


def test_projection_round_trips_through_a_file(tmp_path):
    events = derive_from_ledger("m1", [_ledger_row("g1", i=1, o=2, cost=3), _ledger_row("g2")])
    path = tmp_path / "events.jsonl"
    write_projection(path, events)

    read = read_projection(path)
    assert read.is_intact
    assert read.events == events


def test_regeneration_is_idempotent(tmp_path):
    events = derive_from_ledger("m1", [_ledger_row("g1")])
    path = tmp_path / "events.jsonl"

    write_projection(path, events)
    first = read_projection(path).events
    write_projection(path, events)
    second = read_projection(path).events

    assert first == second, "a derived projection must be safe to rebuild"


def test_a_damaged_line_is_reported_not_skipped(tmp_path):
    path = tmp_path / "events.jsonl"
    write_projection(path, derive_from_ledger("m1", [_ledger_row("g1"), _ledger_row("g2")]))

    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = "{ not json"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    read = read_projection(path)
    assert not read.is_intact, "a corrupt projection must not read as merely smaller"
    assert read.unreadable == [1]
    assert len(read.events) == 3, "the readable events are still returned"


def test_a_missing_projection_is_empty_and_intact(tmp_path):
    read = read_projection(tmp_path / "never-written.jsonl")

    assert read.events == []
    assert read.is_intact, "nothing derived yet is not corruption"


def test_projection_queries(tmp_path):
    events = derive_from_ledger("m1", [_ledger_row("g1"), _ledger_row("g2")])
    p = Projection(events=list(events))

    assert len(p.of_kind(EventKind.GOAL_FINISHED)) == 2
    assert len(p.for_goal("g1")) == 2
    assert p.for_goal("nobody") == []
