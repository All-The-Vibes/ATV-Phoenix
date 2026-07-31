"""Derive typed mission events from Phoenix's canonical evidence.

Phoenix already records everything that matters: hash-chained traces, proof bundles, the run
ledger. What it lacks is a way to *ask questions* of that record. Answering "what is our proof
coverage" by re-reading raw trace files is a query engine implemented by hand, badly, every time.

This module derives a typed event stream from the canonical sources. The events are a
**projection**, never the source of truth — the trace and the ledger stay canonical. That
distinction is load-bearing: a projection can be deleted and rebuilt from evidence, so a bug here
costs a regeneration, not an audit trail. Anything that cannot be rederived does not belong here.

Stored as JSONL. No database, per #83's scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator, Sequence


class EventKind(str, Enum):
    """The typed event vocabulary #83 asks for.

    Deliberately closed: an open string field would let each producer invent its own spelling of
    "the gate failed", and the aggregate metrics would silently undercount.
    """

    MISSION_STARTED = "mission_started"
    MISSION_FINISHED = "mission_finished"
    GOAL_STARTED = "goal_started"
    GOAL_FINISHED = "goal_finished"
    BACKEND_SELECTED = "backend_selected"
    GATE_EVALUATED = "gate_evaluated"
    HEAL_ATTEMPTED = "heal_attempted"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    INTEGRATION_COMPLETED = "integration_completed"


@dataclass(frozen=True)
class Event:
    """One derived fact about a mission.

    `ok` is tri-state on purpose: ``None`` means the event has no pass/fail semantics (a mission
    starting is neither), which is different from ``False``. Collapsing them would make every
    non-outcome event count as a failure in any naive aggregate.
    """

    kind: EventKind
    mission: str
    goal: str | None = None
    ok: bool | None = None
    backend: str | None = None
    detail: str | None = None
    tokens: int | None = None
    cost_micros: int | None = None

    def to_json(self) -> str:
        d = {k: v for k, v in asdict(self).items() if v is not None}
        d["kind"] = self.kind.value
        return json.dumps(d, sort_keys=True)

    @staticmethod
    def from_json(line: str) -> "Event":
        d = json.loads(line)
        return Event(
            kind=EventKind(d["kind"]),
            mission=d["mission"],
            goal=d.get("goal"),
            ok=d.get("ok"),
            backend=d.get("backend"),
            detail=d.get("detail"),
            tokens=d.get("tokens"),
            cost_micros=d.get("cost_micros"),
        )


@dataclass
class Projection:
    """A regenerable event stream plus the lines that could not be read.

    Unreadable lines are surfaced, not skipped — the same rule the run ledger and (since #111) the
    trace chain follow. A projection that silently drops damaged rows reads as merely smaller, and
    every metric computed from it is quietly wrong.
    """

    events: list[Event] = field(default_factory=list)
    unreadable: list[int] = field(default_factory=list)

    @property
    def is_intact(self) -> bool:
        return not self.unreadable

    def of_kind(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind is kind]

    def for_goal(self, goal: str) -> list[Event]:
        return [e for e in self.events if e.goal == goal]


def derive_from_ledger(mission: str, entries: Iterable[dict]) -> list[Event]:
    """Derive backend-selection and goal-outcome events from run-ledger rows.

    The ledger is canonical; this reads it and emits typed facts. A row that records an error
    yields a failed goal event, and one backend-selection event is emitted per row because
    "we chose cloud and it failed" is itself a fact worth counting.
    """
    out: list[Event] = []
    for row in entries:
        goal = row.get("goal")
        backend = row.get("backend")
        if backend:
            out.append(
                Event(
                    kind=EventKind.BACKEND_SELECTED,
                    mission=mission,
                    goal=goal,
                    backend=backend,
                )
            )
        tokens = None
        i, o = row.get("input_tokens"), row.get("output_tokens")
        if i is not None and o is not None:
            tokens = i + o
        out.append(
            Event(
                kind=EventKind.GOAL_FINISHED,
                mission=mission,
                goal=goal,
                ok=row.get("error") is None,
                backend=backend,
                detail=row.get("error"),
                tokens=tokens,
                cost_micros=row.get("cost_micros"),
            )
        )
    return out


def write_projection(path: Path, events: Sequence[Event]) -> None:
    """Write the projection as JSONL, replacing any previous one.

    Overwriting is safe *because* this is derived: the canonical evidence is untouched, so a
    regeneration is idempotent rather than destructive. The run ledger, which is not derived, is
    append-only for exactly the opposite reason.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(e.to_json() + "\n")


def read_projection(path: Path) -> Projection:
    """Read a projection, reporting unreadable lines rather than dropping them."""
    p = Projection()
    if not path.exists():
        return p
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            p.events.append(Event.from_json(line))
        except (json.JSONDecodeError, KeyError, ValueError):
            p.unreadable.append(i)
    return p


def _iter_events(source: Projection | Iterable[Event]) -> Iterator[Event]:
    return iter(source.events if isinstance(source, Projection) else source)


def sanitize_for_telemetry(event: Event) -> dict:
    """Return a minimal telemetry payload safe for local/PostHog projection.

    `detail` is intentionally omitted because it can contain raw backend error text. The goal of
    this projection is mission-level observability, not log shipping.
    """
    payload = json.loads(event.to_json())
    payload.pop("detail", None)
    return payload


def project_telemetry(
    source: Projection | Iterable[Event], *, posthog_enabled: bool
) -> dict[str, list[dict]]:
    """Project sanitized events to local storage and optional PostHog sink."""
    local = [sanitize_for_telemetry(event) for event in _iter_events(source)]
    return {
        "local": local,
        "posthog": list(local) if posthog_enabled else [],
    }
