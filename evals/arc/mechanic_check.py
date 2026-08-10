"""Does a rule of the game survive the level boundary, and can it still be dropped?

Free: no environment, no API, no actions. Run before spending a paid run.

The defect this pins down was measured on su15. At one level change the agent was told
it had "retired 59 belief(s) earned on the previous board; they must be re-earned here",
and among the 59 was "a black obstacle on a particle's predicted northwest cell reflects
that particle". That is not a fact about level 1's layout, it is how the game works, and
re-earning it is paid for in actions -- the one quantity RHAE squares. The run then spent
1,044 of its 1,055 actions on the level that followed and finished 2 of 9.

Scoping beliefs to the level is still right. The fix is not to widen the scope but to let
the agent say which claims were never about the board in the first place.
"""

from __future__ import annotations

from phoenix_learn.accept import BeliefStore


def check_board_facts_still_die() -> None:
    """The original fix must survive: an ungated claim does NOT cross a boundary."""
    store = BeliefStore(scope=("level", 1))
    store.observe("the exit is in the top-right corner", False)
    store.observe("the exit is in the top-right corner", True)

    dropped = store.enter(("level", 2))

    assert dropped == ["the exit is in the top-right corner"], dropped
    assert "the exit is in the top-right corner" not in store.beliefs
    print("  board facts still retired at the boundary   OK")


def check_a_law_survives() -> None:
    """A claim marked durable crosses, and brings its evidence rather than a bare string."""
    store = BeliefStore(scope=("level", 1))
    law = "an obstacle reflects a particle"
    store.observe(law, False)
    store.observe(law, True)
    kept = store.keep(law)
    assert kept["ok"], kept

    # Something board-shaped alongside it, to prove the split is real and not "keep all".
    store.observe("the exit is top-right", True)

    dropped = store.enter(("level", 2))

    assert dropped == ["the exit is top-right"], dropped
    assert law in store.beliefs, "the law was retired with the board facts"
    verdict = store.accept(law)
    assert verdict["ok"], verdict
    assert verdict["saw_red"], "evidence did not cross with the claim"
    # It now belongs to the level it is being used on, so a later boundary is not a
    # second chance to retire it.
    assert store.beliefs[law].scope == ("level", 2), store.beliefs[law].scope
    print("  a law crosses the boundary WITH its evidence  OK")


def check_a_law_is_still_falsifiable() -> None:
    """Durable is not a promotion to true. A later red still refutes it."""
    store = BeliefStore(scope=("level", 1))
    law = "action 3 moves you north"
    store.observe(law, False)
    store.observe(law, True)
    store.keep(law)
    store.enter(("level", 2))

    store.observe(law, False)  # level 2 says otherwise

    verdict = store.accept(law)
    assert not verdict["ok"], "a durable belief refused to be refuted"
    assert not verdict["currently_green"], verdict
    print("  a durable law can still be refuted            OK")


def check_keep_refuses_an_untested_claim() -> None:
    """You cannot preserve evidence for a claim nobody ever tested."""
    store = BeliefStore(scope=("level", 1))
    out = store.keep("the game is secretly chess")
    assert not out["ok"], out
    assert "never observed" in out["why"], out
    print("  keep() refuses an untested claim              OK")


def check_the_agent_facing_split() -> None:
    """Env.mechanic survives a level change; Env.note does not."""
    from evals.arc.codeact_agent import Env

    env = Env.__new__(Env)
    env.notes = []
    env.level_notes = []
    env.mechanics_learned = []
    env.retracted = []
    env._keep = lambda claim: {"ok": False, "why": "not attached"}

    env.note("the exit is at (3, 61)")
    env.mechanic("obstacles reflect particles")

    # What the level advance does, per Env.step.
    env.level_notes = []
    env.retracted = []

    assert env.level_notes == []
    assert env.mechanics_learned == ["obstacles reflect particles"]

    dup = env.mechanic("obstacles reflect particles")
    assert not dup["ok"], "the same law was recorded twice"

    gone = env.unmechanic(1, because="level 3 particles pass straight through")
    assert gone["ok"], gone
    assert env.mechanics_learned == []
    assert any("DISPROVED" in r for r in env.retracted), env.retracted
    assert not env.unmechanic(1)["ok"], "dropped a mechanic that no longer exists"
    print("  mechanic() lives, note() dies, both droppable OK")


if __name__ == "__main__":
    print("game rules vs board facts:")
    check_board_facts_still_die()
    check_a_law_survives()
    check_a_law_is_still_falsifiable()
    check_keep_refuses_an_untested_claim()
    check_the_agent_facing_split()
    print("all green")
