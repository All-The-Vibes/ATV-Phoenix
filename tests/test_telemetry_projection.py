"""Real coverage for the telemetry projection added alongside the #130 proof.

phoenix_learn/events.py gained sanitize_for_telemetry and project_telemetry in commit 0593752.
The only thing that referenced project_telemetry was tests/test_hybrid_mission_e2e.py, which
asserted list lengths and nothing about content. sanitize_for_telemetry had no references at all.
Removing that file under issue #139 would leave both functions untested, so this replaces the
coverage with assertions about what the functions are for.

The property that matters is the detail field. Backend error text can carry raw command output
and paths, and the projection exists for mission level observability rather than log shipping.
"""

from __future__ import annotations

from phoenix_learn.events import (
    Event,
    EventKind,
    Projection,
    project_telemetry,
    sanitize_for_telemetry,
)


def _event(**kwargs) -> Event:
    base = dict(kind=EventKind.GATE_EVALUATED, mission="m-1", goal="g1", ok=True)
    base.update(kwargs)
    return Event(**base)


def test_sanitize_drops_detail_because_it_can_carry_raw_backend_output():
    event = _event(detail="thread panicked at src/lease.rs:88, token=ghp_secretish")
    payload = sanitize_for_telemetry(event)
    assert "detail" not in payload
    assert payload["mission"] == "m-1"
    assert payload["goal"] == "g1"


def test_sanitize_keeps_the_fields_observability_actually_needs():
    payload = sanitize_for_telemetry(_event())
    assert payload["kind"] == EventKind.GATE_EVALUATED.value
    assert payload["ok"] is True


def test_posthog_is_opt_in_and_local_is_always_written():
    events = [_event(goal="a"), _event(goal="b")]
    off = project_telemetry(events, posthog_enabled=False)
    assert len(off["local"]) == 2
    assert off["posthog"] == []
    on = project_telemetry(events, posthog_enabled=True)
    assert len(on["posthog"]) == 2


def test_the_posthog_copy_is_sanitized_too_not_just_the_local_one():
    events = [_event(detail="raw stderr with a path C:/Users/someone/secret")]
    projected = project_telemetry(events, posthog_enabled=True)
    assert all("detail" not in row for row in projected["local"])
    assert all("detail" not in row for row in projected["posthog"])


def test_a_projection_object_is_accepted_as_well_as_a_plain_iterable():
    events = [_event(goal="a")]
    from_iterable = project_telemetry(events, posthog_enabled=False)
    from_projection = project_telemetry(Projection(events=events), posthog_enabled=False)
    assert from_iterable == from_projection
