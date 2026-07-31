"""Privacy-safe optional PostHog sink for derived observability events."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

_ABS_PATH_RE = re.compile(r"^(?:[a-zA-Z]:[\\/]|/)")
_FORBIDDEN_KEYS = {
    "source",
    "source_code",
    "code",
    "prompt",
    "command",
    "command_output",
    "stdout",
    "stderr",
    "trace",
    "trace_evidence",
    "evidence",
    "path",
    "private_path",
}
_ALLOWED_KEYS = {
    "event",
    "mission_id",
    "goal_id",
    "run_id",
    "session_id",
    "task_id",
    "timestamp",
    "backend",
    "provider",
    "model",
    "outcome",
    "outcome_category",
    "duration_ms",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_micros",
    "cost_usd",
    "retry_count",
    "error_kind",
    "hashes",
    "alerts",
}


class PostHogClient(Protocol):
    def capture(self, distinct_id: str, event: str, properties: Mapping[str, Any]) -> Any: ...

    def flush(self) -> Any: ...


@dataclass
class _Envelope:
    distinct_id: str
    event: str
    properties: dict[str, Any]
    attempts: int = 0


@dataclass
class PostHogSink:
    """Buffered sink that never makes PostHog availability a correctness dependency."""

    client: PostHogClient | None = None
    max_retries: int = 3
    fallback_path: Path | None = None
    repository: str | None = None
    organization: str | None = None
    run_experiments: Mapping[str, str] = field(default_factory=dict)
    _queue: deque[_Envelope] = field(default_factory=deque, init=False)

    def emit(self, payload: Mapping[str, Any]) -> None:
        """Queue and attempt to deliver a sanitized event. Never raises."""
        safe = _sanitize_payload(payload)
        if not safe:
            return
        distinct_id = str(safe.get("mission_id") or safe.get("run_id") or "anonymous")
        event = str(safe.pop("event", "phoenix_event"))
        safe["experiment_assignments"] = dict(self.run_experiments)
        safe["groups"] = {
            "repository": self.repository,
            "organization": self.organization,
        }
        envelope = _Envelope(distinct_id=distinct_id, event=event, properties=safe)
        self._queue.append(envelope)
        self.flush()

    def flush(self) -> None:
        """Try sending queued events. Failures stay buffered and are mirrored locally."""
        while self._queue:
            current = self._queue[0]
            try:
                if self.client is None:
                    raise RuntimeError("posthog client unavailable")
                self.client.capture(
                    distinct_id=current.distinct_id,
                    event=current.event,
                    properties=current.properties,
                )
                self.client.flush()
                self._queue.popleft()
            except Exception:
                current.attempts += 1
                self._write_fallback(current, exhausted=current.attempts > self.max_retries)
                if current.attempts > self.max_retries:
                    self._queue.popleft()
                break

    @property
    def pending(self) -> int:
        return len(self._queue)

    def _write_fallback(self, envelope: _Envelope, *, exhausted: bool) -> None:
        if self.fallback_path is None:
            return
        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "captured_at": datetime.now(UTC).isoformat(),
            "event": envelope.event,
            "distinct_id": envelope.distinct_id,
            "attempts": envelope.attempts,
            "exhausted": exhausted,
            "properties": envelope.properties,
        }
        with self.fallback_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _FORBIDDEN_KEYS or key not in _ALLOWED_KEYS:
            continue
        if isinstance(value, str) and _ABS_PATH_RE.match(value):
            continue
        if key == "alerts":
            safe[key] = _sanitize_alerts(value)
            continue
        if key == "hashes":
            safe[key] = _sanitize_hashes(value)
            continue
        safe[key] = value
    return safe


def _sanitize_hashes(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, item in value.items():
        if key in {"trace", "ledger", "prompt", "command", "artifact"} and isinstance(item, str):
            out[str(key)] = item
    return out


def _sanitize_alerts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        category = item.get("category")
        severity = item.get("severity")
        if isinstance(category, str) and isinstance(severity, str):
            out.append({"category": category, "severity": severity})
    return out
