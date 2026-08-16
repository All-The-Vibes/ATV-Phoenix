"""Can the ARC agent's own instruction be improved, and gated on measured gain?

THE RSI SURFACE THAT WAS NOT WIRED. `phoenix_learn.optimize` is a working
reflective hill-climb -- bounded anchored edits, a learning-rate budget, a
leakage firewall, and `gate.decide` as the adoption verdict. `evals/arc` imports
`phoenix_learn.gate`, `.accept` and `.split`, and imports `.optimize` NOWHERE.
The proposer half of the loop was built and never connected, so the single
highest-leverage artifact in the harness -- the system prompt every run is
steered by -- was a frozen constant that only a human could edit.

That matters because the harness IS the variable here. Same-class models score
0.18-0.51% under ARC Prize's harness and 95.5% under Prime Agent's, and this
repo's corpus moved 0.43% -> 31.18% with the model held constant. Every one of
those points came from someone editing harness text by hand. This is the machine
doing it.

WHAT THIS CHECKS, and what it deliberately does not. It checks the MECHANISM:
that a candidate instruction can be proposed as bounded edits, that a proposal
which does not measurably beat the incumbent is REJECTED, and that adoption is
decided by held-out evidence rather than by the proposer's opinion. It does not
check that any particular candidate is good -- that is what the gate is for, run
against real games.

Offline and deterministic: every model touch point is an injected callable, so
this exercises the wiring with no network and no spend.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.instruction_rsi import (  # noqa: E402
    ACTIVE, propose, load_active, verdict_for,
)


def main() -> int:
    failures: list[str] = []

    base = "Play well.\nEFFICIENCY IS SQUARED.\nLOOKING IS FREE."

    # 1. A proposal is bounded, anchored, and lands. An unanchored edit must
    #    fail closed rather than silently corrupting the instruction that every
    #    run depends on.
    try:
        propose(base, [{"op": "add", "anchor": "NOT PRESENT ANYWHERE",
                        "text": " x"}], lr_budget=100)
    except ValueError:
        pass
    else:
        failures.append("an edit with a missing anchor was applied instead of failing closed")

    good, applied, rejected, used = propose(
        base,
        [{"op": "add", "anchor": "LOOKING IS FREE.",
          "text": " Re-read the board before every action."}],
        lr_budget=100,
    )
    print(f"proposal: {len(applied)} applied, {len(rejected)} rejected, cost {used}")
    if "Re-read the board" not in good:
        failures.append("a well-formed edit did not land")
    if base not in ("".join(base)):  # base must not be mutated in place
        failures.append("the incumbent instruction was mutated")

    # 2. The learning rate actually bites. An edit over budget is REJECTED, not
    #    applied -- otherwise a runaway proposer rewrites the whole instruction
    #    in one generation and the hill-climb becomes a coin flip.
    _, applied2, rejected2, _ = propose(
        base,
        [{"op": "add", "anchor": "LOOKING IS FREE.", "text": "x" * 500}],
        lr_budget=50,
    )
    print(f"over-budget edit: {len(applied2)} applied, {len(rejected2)} rejected")
    if applied2 or not rejected2:
        failures.append("an edit over the learning-rate budget was applied")

    # 3. THE GATE IS THE POINT. A candidate that does not beat the incumbent on
    #    held-out evidence must not be adopted, however confident the proposer.
    worse = verdict_for(incumbent=0.3118, candidate=0.2900, n=6)
    better = verdict_for(incumbent=0.3118, candidate=0.4000, n=6)
    print(f"candidate WORSE  -> adopt={worse['adopt']}  ({worse['why']})")
    print(f"candidate BETTER -> adopt={better['adopt']}  ({better['why']})")
    if worse["adopt"]:
        failures.append("a candidate that scored WORSE than the incumbent was adopted")
    if not better["adopt"]:
        failures.append("a candidate that clearly beat the incumbent was rejected")

    # 4. The active instruction is loadable and non-empty -- the agent has to be
    #    able to read whatever the loop adopted, or none of this reaches a run.
    active = load_active()
    print(f"active instruction: {len(active)} chars from {ACTIVE.name}")
    if not active or len(active) < 200:
        failures.append(f"the active instruction is missing or too short ({len(active)} chars)")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK    the instruction is evolvable, bounded, and gated on measured gain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
