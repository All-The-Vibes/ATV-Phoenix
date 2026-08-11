"""Cross-episode memory that a fact has to earn its way into. Issue #186.

Phoenix can verify a claim and then forgets it. Every domain that needed to carry something
into the next run built its own store: `evals/arc/skills.py` holds `name, game, source,
description, tags` and filters on `game`, which is useful to ARC and useless to a shell agent
or a refactoring agent. This module is the domain-agnostic version, and it keeps the two
properties the ARC library does not have.

**A fact enters only by clearing the acceptance rule.** `remember` takes the trials behind a
claim and runs them through `phoenix_learn.accept.verify_gate`, the same function
`tests/test_accept_parity.py` and `tests/accept_parity.rs` pin to `src/accept.rs`. A claim
that was never seen failing is vacuous here for the same reason it is vacuous at a merge gate,
so asserting a fact does not store it. There is no argument that skips the gate.

**A fact is keyed by scope and can be retired.** `enter(scope)` drops everything earned under
the previous scope, matching `BeliefStore.enter` in `accept.py`. #181 is the measured cost of
not having that: an ARC agent kept applying level-1 geometry to level 2 and spent seven
consecutive turns taking 0-2 actions, and one turn spending 2,075 actions permuting a theory
that could not be true. A memory with no delete accumulates false facts, which is why #186
says this and the belief scope work land together.

The admitting evidence stays with the fact. `evidence(key)` returns the trials and the gate
verdict that let it in, so a stored fact can be audited later instead of being taken on trust,
and re-earning after a scope change is one confirming trial rather than a rediscovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from phoenix_learn.accept import Observation, verify_gate

__all__ = ["Fact", "Memory"]


@dataclass
class Fact:
    """One remembered claim, the scope it holds in, and why it was admitted."""

    key: str
    value: Any
    scope: Any = None
    trials: list[Observation] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)

    @property
    def reason(self) -> str:
        return self.verdict.get("reason", "")


class Memory:
    """A store whose only way in is the failure-first gate.

    Three calls: `enter(scope)` when the world changes, `remember(key, value, trials)` to
    offer a fact, `recall(key)` to read one back. `remember` returns the same shape
    `verify_gate` returns plus the stored fact, so a caller that ignores the return value
    cannot mistake a refusal for a write.
    """

    def __init__(self, scope: Any = None) -> None:
        self.scope = scope
        self.facts: dict[str, Fact] = {}

    def remember(self, key: str, value: Any, trials, scope: Any = None) -> dict:
        """Offer a fact. It is stored only if `trials` clears the acceptance rule.

        `trials` is a sequence of `Observation` or plain bools, oldest first, exactly what
        `verify_gate` takes. Passing an empty sequence, or only greens, is refused: a claim
        never seen failing proves nothing.
        """
        verdict = verify_gate(trials)
        if not verdict["ok"]:
            return {**verdict, "stored": False, "fact": None}

        obs = [t if isinstance(t, Observation) else Observation(bool(t)) for t in trials]
        fact = Fact(
            key=key,
            value=value,
            scope=self.scope if scope is None else scope,
            trials=obs,
            verdict=dict(verdict),
        )
        self.facts[key] = fact
        return {**verdict, "stored": True, "fact": fact}

    def recall(self, key: str) -> Fact | None:
        """Return the fact if it is held in the CURRENT scope, else None.

        A fact earned in another scope is not returned. It is not true here until it has been
        re-earned, which is the rule #181 asks for stated for storage rather than for beliefs.
        """
        fact = self.facts.get(key)
        if fact is None or fact.scope != self.scope:
            return None
        return fact

    def evidence(self, key: str) -> dict | None:
        """The trials and the gate verdict that admitted `key`, for auditing it later.

        Unlike `recall`, this answers across scopes: the point of keeping the evidence is that
        a fact retired by a scope change can be restored by one confirming trial instead of
        being rediscovered from nothing.
        """
        fact = self.facts.get(key)
        if fact is None:
            return None
        return {
            "key": fact.key,
            "scope": fact.scope,
            "trials": [t.ok for t in fact.trials],
            "verdict": dict(fact.verdict),
        }

    def enter(self, scope: Any) -> list[str]:
        """Move to a new scope. Returns the keys that stopped being current.

        Facts are kept, not deleted, so `evidence` still answers for them and re-earning is
        cheap. What changes is that `recall` and `known` no longer report them.
        """
        if scope == self.scope:
            return []
        dropped = sorted(k for k, f in self.facts.items() if f.scope == self.scope)
        self.scope = scope
        return dropped

    def known(self) -> list[str]:
        """Keys held in the current scope, sorted."""
        return sorted(k for k, f in self.facts.items() if f.scope == self.scope)

    def summary(self) -> str:
        held = self.known()
        if not held:
            return f"MEMORY[{self.scope}]: nothing earned in this scope."
        lines = [f"MEMORY[{self.scope}] (a fact is stored only after it was seen WRONG):"]
        for key in held:
            fact = self.facts[key]
            lines.append(f"  {key} = {fact.value!r}  [{fact.reason}]")
        return "\n".join(lines)
