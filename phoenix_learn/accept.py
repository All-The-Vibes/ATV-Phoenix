"""Failure-first acceptance and scoped beliefs, in Python. Issues #181 and #182.

Two things lived in the wrong place before this module existed.

**Failure-first was Rust-only.** `src/accept.rs` owns the rule: a check counts as passed
only when the trace shows it observed RED, then GREEN after that red, and is green now
(`saw_red`, `green_after_red`, `currently_green`). That code is reachable only over MCP,
from an agent's tool call, so `evals/arc/phoenix_loop.py` hand-rolled a second copy in
Python. The copy had already drifted: it added a `green >= 2` requirement the Rust side
does not have, so the same evidence was accepted by one and refused by the other. One
honesty core, one implementation. `tests/test_accept_parity.py` pins the two together.

**Nothing retired a belief.** Phoenix could create and read a fact and never delete one.
When the ARC level changed, level-1 facts stayed marked PROVEN and the agent applied them
to a board where they were false; that is the measured cause of the observed
`verification mismatch; no action` and of a 2,075-action turn spent defending a dead
theory. A belief here carries a SCOPE, and when the scope changes every belief under it
drops back to unproven and has to be re-earned from new evidence.

Seeds are recorded on every observation (issue #185). A check that cannot name the seed
it ran under is reported as unreproducible rather than as green, because the same ARC
config produced level-1 action counts of 69, 17 and 83, and one green run under an
unknown seed distinguishes nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Returned in `reason` when a claim has only ever been seen passing. Phoenix calls this
#: vacuous rather than proven: a gate never observed failing tests nothing.
VACUOUS = "vacuous: never observed failing"


@dataclass(frozen=True)
class Observation:
    """One trial of a claim, with the seed that produced it."""

    ok: bool
    seed: int | None = None
    note: str = ""


@dataclass
class Belief:
    """A claim, the trials behind it, and the scope it is only valid within.

    `scope` is any hashable label for the world the claim describes: an ARC level, a
    git ref, a hostname. Beliefs are dropped when their scope stops being current.
    """

    claim: str
    scope: object = None
    trials: list[Observation] = field(default_factory=list)

    @property
    def red(self) -> int:
        return sum(1 for t in self.trials if not t.ok)

    @property
    def green(self) -> int:
        return sum(1 for t in self.trials if t.ok)

    @property
    def seeds(self) -> set:
        return {t.seed for t in self.trials if t.seed is not None}


def verify_gate(trials) -> dict:
    """The failure-first rule, matching `src/accept.rs::verify_gate`.

    `trials` is a sequence of `Observation` (or plain bools). Returns the same shape the
    Rust gate returns so a Python caller and an MCP caller can be compared directly.

    Deliberately does NOT require two greens. The Python copy in `phoenix_loop.py` did,
    which meant a claim the Rust gate accepted was refused here, and "proven" meant two
    different things in one repo depending on which language asked.
    """
    obs = [t if isinstance(t, Observation) else Observation(bool(t)) for t in trials]
    saw_red = False
    green_after_red = False
    for trial in obs:
        if not trial.ok:
            saw_red = True
        elif saw_red:
            green_after_red = True
    currently_green = bool(obs) and obs[-1].ok

    if not obs:
        reason = "never tested"
    elif not saw_red:
        reason = VACUOUS
    elif not currently_green:
        reason = "currently red"
    elif not green_after_red:
        reason = "no red -> green transition"
    else:
        reason = f"{sum(1 for t in obs if not t.ok)}R/{sum(1 for t in obs if t.ok)}G failure-first"

    return {
        "ok": saw_red and green_after_red and currently_green,
        "saw_red": saw_red,
        "green_after_red": green_after_red,
        "currently_green": currently_green,
        "reason": reason,
    }


class BeliefStore:
    """Scoped beliefs with the missing DELETE.

    Usage is three calls: `enter(scope)` when the world changes, `observe(...)` for each
    trial, `accept(...)` to ask whether a claim is established. Entering a new scope
    retires every belief recorded under the old one, so a fact earned on level 1 cannot
    silently govern level 2.
    """

    def __init__(self, scope=None, min_seeds: int = 0):
        #: Distinct seeds required before a stochastic claim counts as reproducible.
        #: 0 is off, which keeps deterministic callers working unchanged; ARC adoption
        #: decisions pass 3. It is deliberately NOT 1: a default of 1 would demand a
        #: NAMED seed from every caller, so an ordinary unseeded red->green would be
        #: reported unreproducible and the honest gate would start refusing real work.
        self.min_seeds = min_seeds
        self.scope = scope
        self.beliefs: dict[str, Belief] = {}
        self.retired: list[Belief] = []

    def enter(self, scope) -> list[str]:
        """Move to a new scope, retiring every belief held under the old one.

        Returns the claims that were dropped, so the caller can say plainly what it just
        stopped believing instead of carrying it forward unannounced.
        """
        if scope == self.scope:
            return []
        dropped = sorted(self.beliefs)
        self.retired.extend(self.beliefs.values())
        self.beliefs = {}
        self.scope = scope
        return dropped

    def observe(self, claim: str, ok: bool, seed: int | None = None, note: str = "") -> Belief:
        belief = self.beliefs.setdefault(claim, Belief(claim=claim, scope=self.scope))
        belief.trials.append(Observation(bool(ok), seed, note))
        return belief

    def accept(self, claim: str) -> dict:
        """Is this claim established here and now?

        Adds one condition to the failure-first rule: the evidence must name enough
        distinct seeds. An unseeded green is reported as unreproducible, not as ok.
        """
        belief = self.beliefs.get(claim)
        if belief is None:
            return {"ok": False, "reason": "never tested", "scope": self.scope}
        verdict = verify_gate(belief.trials)
        verdict["scope"] = self.scope
        if verdict["ok"] and len(belief.seeds) < self.min_seeds:
            verdict["ok"] = False
            verdict["reason"] = (
                f"unreproducible: {len(belief.seeds)} distinct seed(s), "
                f"need {self.min_seeds}"
            )
        return verdict

    def established(self) -> list[str]:
        return sorted(c for c in self.beliefs if self.accept(c)["ok"])

    def summary(self) -> str:
        if not self.beliefs:
            return f"PHOENIX[{self.scope}]: nothing tested in this scope."
        lines = [
            f"PHOENIX[{self.scope}] (a claim counts only once it has been seen WRONG):"
        ]
        for claim, belief in sorted(self.beliefs.items()):
            verdict = self.accept(claim)
            mark = "PROVEN" if verdict["ok"] else "unproven"
            lines.append(
                f"  [{mark}] {claim}  ({belief.red}R/{belief.green}G: {verdict['reason']})"
            )
        return "\n".join(lines)
