"""Phoenix inside the ARC agent's own loop, not scoring it from outside.

Until now Phoenix graded ARC after the fact: `heldout_gate.py` read a results file and
`gate_sb26.py` printed GREEN or RED once the run was over. Nothing in the agent consulted
it while playing, so the agent's beliefs were never held to the same standard as the
repo's code. That is exactly how nine runs recorded confident, unverified mechanics and
then defended them for thousands of actions.

Two Phoenix disciplines are wired in here:

**Failure-first evidence.** A belief is only written to the skill library once it has been
observed RED and then GREEN. `phoenix_accept` refuses a check that was never seen failing,
calling it vacuous; the same rule applies to a claim about the game. "Action 5 submits"
means nothing until you have also seen a submit that did not clear.

That rule is no longer implemented here. It lives in `phoenix_learn.accept`, which
`tests/test_accept_parity.py` pins to `src/accept.rs`. The copy this file used to carry
had drifted: it demanded `green >= 2`, which the Rust gate does not, so the same evidence
was accepted over MCP and refused in-process. Beliefs are also SCOPED now: call
`enter(level)` when the level changes and every belief earned on the old board is retired
rather than silently reapplied to a board where it is false.

**Measured-gain adoption.** `phoenix_learn.gate.decide` is the repo's adoption gate, and
it exists because one green run is not proof: the same config produced level-1 counts of
69, 17 and 83. A hypothesis is adopted here only when its evidence clears that gate,
and the evidence is per-hypothesis trials rather than the agent's own confidence.
"""
from __future__ import annotations

from phoenix_learn.accept import BeliefStore
from phoenix_learn.gate import decide, transitions


class PhoenixLoop:
    """The agent's in-loop acceptance oracle.

    It answers two questions the agent cannot answer about itself: is this belief
    actually established, and is this turn's change worth keeping.
    """

    def __init__(self, scope=None, min_seeds: int = 0):
        self.store = BeliefStore(scope=scope, min_seeds=min_seeds)
        self.turn_records: list[dict] = []

    @property
    def beliefs(self):
        return self.store.beliefs

    # ── beliefs ──────────────────────────────────────────────────────────────────
    def enter(self, scope) -> list[str]:
        """The world changed. Retire what was only true in the old one.

        Returns the dropped claims so the agent can say what it stopped believing.
        """
        return self.store.enter(scope)

    def observe(self, claim: str, passed: bool, seed: int | None = None):
        """Record one trial of a claim. This is the agent's `phoenix_sense`."""
        return self.store.observe(claim, passed, seed=seed)

    def accept(self, claim: str) -> dict:
        """Is this claim proven failure-first? The agent's `phoenix_accept`."""
        return self.store.accept(claim)

    def keep(self, claim: str) -> dict:
        """Carry this claim across level boundaries: it describes the game, not the board."""
        return self.store.keep(claim)

    def established(self) -> list[str]:
        return self.store.established()

    # ── turn-level gain ──────────────────────────────────────────────────────────
    def record_turn(self, turn: int, levels: int, actions: int, wasted: int) -> None:
        self.turn_records.append(
            {"turn": turn, "levels": levels, "actions": actions, "wasted": wasted}
        )

    def adoption_verdict(self, baseline: list[dict], candidate: list[dict]) -> str:
        """Run the repo's real measured-gain gate over per-trial outcomes.

        `baseline` and `candidate` are `[{"intent": str, "ok": bool}, ...]`, one row per
        trial. This is the same call the SIA-H loop makes, unchanged, so an ARC change is
        held to the standard every other change in this repo is held to.
        """
        trans = transitions(baseline, candidate)
        gen0_correct = sum(1 for r in baseline if r["ok"])
        sel_correct = sum(1 for r in candidate if r["ok"])
        n = len(candidate)
        return decide(
            gen0_priv_acc=gen0_correct / len(baseline) if baseline else 0.0,
            sel_priv_acc=sel_correct / n if n else 0.0,
            sel_priv_correct=sel_correct,
            gen0_priv_correct=gen0_correct,
            trans=trans,
            private_n=n,
            gaming_hits=[],
        )

    def summary(self) -> str:
        return self.store.summary()
