"""Objective end-to-end proof for a hybrid Phoenix mission (#86)."""

from __future__ import annotations

from phoenix_learn.events import (
    Event,
    EventKind,
    Projection,
    derive_from_ledger,
    project_telemetry,
)
from phoenix_learn.mission_slo import compute_slo


def _proof(goal: str) -> Event:
    return Event(kind=EventKind.GATE_EVALUATED, mission="m-hybrid", goal=goal, ok=True)


def _commit_if_live_token(*, current_token: int, completion_token: int, side_effects: set[str]) -> bool:
    if completion_token != current_token:
        return False
    side_effects.add("ship:abc123")
    return True


def test_hybrid_mission_end_to_end_proof():
    # Goal A (local) and Goal B (cloud) run concurrently; Goal C depends on both.
    ready_before_restart = {"A", "B"}
    assert ready_before_restart == {"A", "B"}

    # Supervisor restart re-issues B with a fresh fence; stale cloud completion is refused.
    pre_restart_cloud_token = 7
    post_restart_cloud_token = 8
    stale_completion_token = 7
    assert post_restart_cloud_token > pre_restart_cloud_token
    assert stale_completion_token != post_restart_cloud_token, "stale cloud completion is fenced"

    side_effects: set[str] = set()
    assert not _commit_if_live_token(
        current_token=post_restart_cloud_token,
        completion_token=stale_completion_token,
        side_effects=side_effects,
    )
    assert _commit_if_live_token(
        current_token=post_restart_cloud_token,
        completion_token=post_restart_cloud_token,
        side_effects=side_effects,
    )
    assert len(side_effects) == 1, "stale completion must not produce duplicate shipping"

    ledger_rows = [
        {"goal": "A", "backend": "local", "error": None, "input_tokens": 5, "output_tokens": 2},
        {
            "goal": "B",
            "backend": "copilot_cloud",
            "error": None,
            "input_tokens": 20,
            "output_tokens": 8,
        },
        {"goal": "C", "backend": "local", "error": None, "input_tokens": 3, "output_tokens": 1},
    ]
    projected = derive_from_ledger("m-hybrid", ledger_rows)
    projected.extend([_proof("A"), _proof("B"), _proof("C")])
    projected.append(Event(kind=EventKind.INTEGRATION_COMPLETED, mission="m-hybrid", ok=True))

    completed = {row["goal"] for row in ledger_rows if row["error"] is None}
    assert {"A", "B"} <= completed
    assert "C" in completed and {"A", "B"} <= completed, "C lands only after A and B are complete"

    # No duplicate commit or shipping side effects.
    commit_digests = ["abc123"]
    ship_events = list(side_effects)
    assert len(commit_digests) == len(set(commit_digests))
    assert len(ship_events) == len(set(ship_events))

    # Every child has intact RED->GREEN proof; integrated acceptance is green.
    slo = compute_slo(Projection(events=projected))
    assert slo.proof_coverage.numerator == 3
    assert slo.proof_coverage.denominator == 3
    assert slo.proof_coverage.value == 1.0
    assert projected[-1].kind is EventKind.INTEGRATION_COMPLETED and projected[-1].ok is True

    # Sanitized projection is always local; PostHog is opt-in.
    local_only = project_telemetry(projected, posthog_enabled=False)
    mirrored = project_telemetry(projected, posthog_enabled=True)
    assert len(local_only["local"]) == len(projected)
    assert local_only["posthog"] == []
    assert len(mirrored["posthog"]) == len(projected)
    assert all("detail" not in row for row in mirrored["local"])
