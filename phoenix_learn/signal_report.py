"""Signal → report → outcome helpers for Phoenix learning loops.

Operational signals can be noisy and repetitive. This module keeps the contracts typed and
aggregates repeated signals into deduplicated reports keyed by the acceptance-check digest and
evidence hash, then measures whether merged work moved the target metric.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable


class SignalSource(str, Enum):
    LOCAL_DETECTOR = "local_detector"
    POSTHOG_SCOUT = "posthog_scout"


class MetricDirection(str, Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


@dataclass(frozen=True)
class Signal:
    source: SignalSource
    detector: str
    check_digest: str
    evidence_hash: str
    metric: str
    value: float
    target: float
    direction: MetricDirection = MetricDirection.LOWER_IS_BETTER

    @property
    def dedupe_key(self) -> tuple[str, str]:
        return (self.check_digest, self.evidence_hash)

    @property
    def actionable(self) -> bool:
        if self.direction is MetricDirection.LOWER_IS_BETTER:
            return self.value > self.target
        return self.value < self.target

    def to_json(self) -> str:
        payload = asdict(self)
        payload["source"] = self.source.value
        payload["direction"] = self.direction.value
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def from_json(raw: str) -> "Signal":
        payload = json.loads(raw)
        return Signal(
            source=SignalSource(payload["source"]),
            detector=payload["detector"],
            check_digest=payload["check_digest"],
            evidence_hash=payload["evidence_hash"],
            metric=payload["metric"],
            value=float(payload["value"]),
            target=float(payload["target"]),
            direction=MetricDirection(payload.get("direction", MetricDirection.LOWER_IS_BETTER)),
        )


@dataclass(frozen=True)
class Report:
    check_digest: str
    evidence_hash: str
    metric: str
    latest_value: float
    target: float
    direction: MetricDirection
    signal_count: int
    detectors: tuple[str, ...]
    sources: tuple[SignalSource, ...]
    actionable: bool

    def to_json(self) -> str:
        payload = asdict(self)
        payload["direction"] = self.direction.value
        payload["sources"] = [s.value for s in self.sources]
        return json.dumps(payload, sort_keys=True)


def build_reports(signals: Iterable[Signal]) -> list[Report]:
    groups: dict[tuple[str, str], list[Signal]] = {}
    order: list[tuple[str, str]] = []
    for signal in signals:
        key = signal.dedupe_key
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(signal)

    reports: list[Report] = []
    for key in order:
        grouped = groups[key]
        first = grouped[0]
        for signal in grouped[1:]:
            if signal.metric != first.metric or signal.direction is not first.direction:
                raise ValueError("signals sharing a dedupe key must refer to the same metric contract")
        reports.append(
            Report(
                check_digest=first.check_digest,
                evidence_hash=first.evidence_hash,
                metric=first.metric,
                latest_value=grouped[-1].value,
                target=first.target,
                direction=first.direction,
                signal_count=len(grouped),
                detectors=tuple(sorted({s.detector for s in grouped})),
                sources=tuple(sorted({s.source for s in grouped}, key=lambda s: s.value)),
                actionable=any(s.actionable for s in grouped),
            )
        )
    return reports


@dataclass(frozen=True)
class ProposedIssue:
    state: str
    title: str
    body: str
    blast_radius_max_files: int
    labels: tuple[str, ...]


def propose_issue_from_report(report: Report, *, blast_radius_max_files: int = 3) -> ProposedIssue | None:
    if not report.actionable:
        return None
    title = f"learning: improve {report.metric}"
    body = (
        f"Actionable report for `{report.metric}` from check `{report.check_digest}`.\n"
        f"Latest value {report.latest_value} is off target {report.target}.\n"
        f"Bounded scope budget: <= {blast_radius_max_files} files."
    )
    return ProposedIssue(
        state="proposed",
        title=title,
        body=body,
        blast_radius_max_files=blast_radius_max_files,
        labels=("proposed", "learning"),
    )


def adoption_allowed(change_type: str, gate_decision: str) -> bool:
    guarded = {"skill", "model", "routing"}
    if change_type.lower() not in guarded:
        return True
    return gate_decision == "ADOPT_ELIGIBLE"


@dataclass(frozen=True)
class PostMergeOutcome:
    metric: str
    direction: MetricDirection
    target: float
    before: float
    after: float
    delta: float
    changed: bool
    improved: bool
    met_target: bool


def measure_post_merge_outcome(report: Report, *, before: float, after: float) -> PostMergeOutcome:
    if report.direction is MetricDirection.LOWER_IS_BETTER:
        improved = after < before
        met_target = after <= report.target
    else:
        improved = after > before
        met_target = after >= report.target
    return PostMergeOutcome(
        metric=report.metric,
        direction=report.direction,
        target=report.target,
        before=before,
        after=after,
        delta=after - before,
        changed=after != before,
        improved=improved,
        met_target=met_target,
    )
