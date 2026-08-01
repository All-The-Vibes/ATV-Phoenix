"""Acceptance tests for a privacy-safe optional PostHog sink (#84)."""

from __future__ import annotations

import json

from phoenix_learn.posthog_sink import PostHogSink


class _Client:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls: list[dict] = []

    def capture(self, distinct_id, event, properties):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("posthog down")
        self.calls.append(
            {"distinct_id": distinct_id, "event": event, "properties": dict(properties)}
        )

    def flush(self):
        return None


def test_sink_sends_only_sanitized_derived_fields():
    client = _Client()
    sink = PostHogSink(client=client, repository="All-The-Vibes/ATV-Phoenix", organization="All-The-Vibes")

    sink.emit(
        {
            "event": "goal_finished",
            "mission_id": "m1",
            "backend": "copilot_cloud",
            "model": "gpt-5.6-sol",
            "duration_ms": 1300,
            "cost_micros": 2800,
            "hashes": {"trace": "abc", "ledger": "def"},
            "prompt": "do not leak this",
            "command_output": "private output",
            "path": "/home/runner/private.txt",
            "source_code": "print(secret)",
        }
    )

    sent = client.calls[0]["properties"]
    assert "prompt" not in sent
    assert "command_output" not in sent
    assert "source_code" not in sent
    assert "path" not in sent
    assert sent["hashes"] == {"trace": "abc", "ledger": "def"}
    assert sent["groups"]["repository"] == "All-The-Vibes/ATV-Phoenix"
    assert sent["groups"]["organization"] == "All-The-Vibes"


def test_posthog_outage_never_raises_and_writes_local_fallback(tmp_path):
    sink = PostHogSink(client=_Client(fail_times=99), fallback_path=tmp_path / "posthog-fallback.jsonl")

    sink.emit({"event": "goal_finished", "mission_id": "m1", "outcome_category": "verified"})

    assert sink.pending == 1
    rows = [json.loads(line) for line in sink.fallback_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["event"] == "goal_finished"
    assert rows[-1]["exhausted"] is False


def test_retries_keep_events_buffered_until_a_later_success():
    client = _Client(fail_times=1)
    sink = PostHogSink(client=client, max_retries=3)

    sink.emit({"event": "goal_finished", "mission_id": "m1"})
    assert sink.pending == 1, "first send failed; event stays queued for retry"

    sink.flush()
    assert sink.pending == 0
    assert len(client.calls) == 1


def test_run_level_experiment_assignments_are_frozen():
    client = _Client()
    sink = PostHogSink(client=client, run_experiments={"policy": "A"})

    sink.emit(
        {
            "event": "goal_finished",
            "mission_id": "m1",
            "experiment_assignments": {"policy": "B"},
        }
    )

    assert client.calls[0]["properties"]["experiment_assignments"] == {"policy": "A"}


def test_alert_categories_are_exported_in_sanitized_form():
    client = _Client()
    sink = PostHogSink(client=client)

    sink.emit(
        {
            "event": "alert",
            "mission_id": "m1",
            "alerts": [
                {"category": "proof_coverage", "severity": "high", "detail": "do not export"},
                {"category": "recovery", "severity": "low"},
            ],
        }
    )

    assert client.calls[0]["properties"]["alerts"] == [
        {"category": "proof_coverage", "severity": "high"},
        {"category": "recovery", "severity": "low"},
    ]
