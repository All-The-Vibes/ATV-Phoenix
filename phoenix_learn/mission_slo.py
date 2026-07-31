"""Mission SLOs computed from the derived event projection.

#83 asks for proof coverage, terminal telemetry coverage, recovery rate, intervention rate,
latency, tokens, and cost per verified outcome.

The rule that governs every metric here: **a thin denominator must never pass as green.** AGENTS.md
already says it about silent-failure-rate — "always report coverage beside it" — and it applies to
all of these. A recovery rate of 1.0 computed over one heal attempt is not a good number, it is an
absent one, and a dashboard that renders it as 100% is lying by omission.

So every rate carries its own denominator, and a rate with no denominator is ``None`` rather than
1.0 or 0.0. Callers must decide what to do with "unknown" instead of being handed a fabricated
figure that looks authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events import Event, EventKind, Projection


@dataclass(frozen=True)
class Rate:
    """A ratio that refuses to exist without a denominator.

    ``value`` is ``None`` when nothing was observed. That is deliberately not 0.0 and not 1.0:
    "no runs were measured" and "no runs succeeded" are opposite facts, and a metric type that
    cannot tell them apart will eventually report an outage as perfect health.
    """

    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    @property
    def is_measured(self) -> bool:
        return self.denominator > 0

    def __str__(self) -> str:
        if self.value is None:
            return f"unmeasured (0 observations)"
        return f"{self.value:.3f} ({self.numerator}/{self.denominator})"


@dataclass(frozen=True)
class MissionSlo:
    """The SLO set for one mission. Every rate carries its coverage."""

    proof_coverage: Rate
    terminal_telemetry_coverage: Rate
    recovery_rate: Rate
    intervention_rate: Rate
    total_tokens: int | None
    total_cost_micros: int | None
    verified_outcomes: int

    @property
    def cost_per_verified_outcome(self) -> float | None:
        """Cost per verified outcome, or ``None`` when either side is unknown.

        Returning 0.0 for "nothing verified" would make an entirely failed mission look maximally
        efficient, which is the most dangerous possible direction for this metric to be wrong in.
        """
        if self.total_cost_micros is None or self.verified_outcomes == 0:
            return None
        return self.total_cost_micros / self.verified_outcomes

    @property
    def tokens_per_verified_outcome(self) -> float | None:
        if self.total_tokens is None or self.verified_outcomes == 0:
            return None
        return self.total_tokens / self.verified_outcomes


def compute_slo(projection: Projection) -> MissionSlo:
    """Compute the SLO set from a derived projection."""
    events: list[Event] = projection.events

    goals_finished = [e for e in events if e.kind is EventKind.GOAL_FINISHED]
    gates = [e for e in events if e.kind is EventKind.GATE_EVALUATED]
    heals = [e for e in events if e.kind is EventKind.HEAL_ATTEMPTED]
    approvals = [e for e in events if e.kind is EventKind.APPROVAL_REQUESTED]

    # Proof coverage: of the goals that finished, how many have a gate evaluation at all?
    # A goal that finished without any gate is precisely the silent-failure shape.
    goals_with_gate = {e.goal for e in gates if e.goal is not None}
    proof = Rate(
        numerator=len([g for g in goals_finished if g.goal in goals_with_gate]),
        denominator=len(goals_finished),
    )

    # Terminal telemetry coverage: of goals that finished, how many reported usage?
    terminal = Rate(
        numerator=len([g for g in goals_finished if g.tokens is not None or g.cost_micros is not None]),
        denominator=len(goals_finished),
    )

    # Recovery: of heal attempts, how many succeeded?
    recovery = Rate(numerator=len([h for h in heals if h.ok]), denominator=len(heals))

    # Intervention: of goals that finished, how many needed a human approval?
    goals_needing_approval = {e.goal for e in approvals if e.goal is not None}
    intervention = Rate(
        numerator=len([g for g in goals_finished if g.goal in goals_needing_approval]),
        denominator=len(goals_finished),
    )

    reported_tokens = [g.tokens for g in goals_finished if g.tokens is not None]
    reported_cost = [g.cost_micros for g in goals_finished if g.cost_micros is not None]

    return MissionSlo(
        proof_coverage=proof,
        terminal_telemetry_coverage=terminal,
        recovery_rate=recovery,
        intervention_rate=intervention,
        total_tokens=sum(reported_tokens) if reported_tokens else None,
        total_cost_micros=sum(reported_cost) if reported_cost else None,
        verified_outcomes=len([g for g in goals_finished if g.ok]),
    )
