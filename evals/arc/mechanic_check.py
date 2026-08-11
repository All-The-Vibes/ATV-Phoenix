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


def check_the_doc_says_when_to_write() -> None:
    """Storing correctly is worthless if the agent never reaches the call.

    Every check above pins what happens once `mechanic()` runs, and all of them
    were green while the feature was, in practice, dead. Measured across every
    trace on disk: 249 writes attempted, 190 placed under `if levels() > start:`
    and 217 placed after a press() or click() in the same turn.

    Gating on a level clear is a deadlock -- on a game you are losing no turn
    clears a level, so no rule is ever kept, and that is exactly the game whose
    rules you need. One run attempted 84 writes, cleared nothing while making
    them, and stored none; bp35 attempted 17, stored none, and spent the run
    proposing six contradictory theories of the same game.

    The doc said what a mechanic IS and never said when to record one, so the
    agent invented a rule and the rule it invented was fatal. This pins the
    live prompt text rather than a copy, for the reason congestion_check.py
    gives: the thing that rotted was prose, and a transcription of prose inside
    a test stays green while the original decays.
    """
    import re

    from evals.arc.codeact_agent import SYSTEM

    assert "mechanic(text)" in SYSTEM, "the API block no longer documents mechanic(text)"
    start = SYSTEM.index("mechanic(text)")
    # Bound the window at the next entry rather than a character count, so the
    # check reads exactly the paragraph the agent reads and cannot start passing
    # because some unrelated line drifted inside an arbitrary radius.
    end = SYSTEM.index("unmechanic(", start)
    entry = SYSTEM[start:end]

    required = {
        "that the write must precede the action": r"BEFORE you spend|ABOVE the actions",
        "that gating on a level clear is the trap": r"levels\(\)\s*>\s*start",
        "what gating cost": r"\b190\b",
        "what writing after an action cost": r"\b217\b",
        "that the observation is the evidence": r"movement diff|from the observation",
    }
    for what, pattern in required.items():
        assert re.search(pattern, entry), f"the mechanic() doc no longer says {what}"
    print("  the doc says WHEN to write, not just what     OK")


def check_death_names_the_write_it_just_destroyed() -> None:
    """A death raises at the killing action; everything below it is discarded.

    So a conclusion written at the bottom of a turn -- which is where 217 of 249
    of them were written -- is destroyed by the very event that taught it. The
    death message is the one place the agent is certain to read at that moment,
    so it must say so there, and only when the symptom is present: an agent that
    is recording correctly does not need the paragraph, and advice printed on
    every death is advice learned to skip.
    """
    import inspect
    import re

    from evals.arc.codeact_agent import Env

    src = inspect.getsource(Env._step)
    assert "NEVER RAN" in src, "the death message no longer names the discarded write"

    guard = re.search(
        r"if\s+self\.mechanics_learned\s*==\s*\[\]\s*and\s+self\.deaths\s*>=\s*(\d+)", src
    )
    assert guard, (
        "the warning is no longer conditioned on an empty mechanics list plus "
        "repeated deaths -- unconditional, it is noise on runs already doing it right"
    )
    assert int(guard.group(1)) >= 2, (
        "the warning fires on the first death, before the pattern it describes exists"
    )
    print("  death names the lesson it just discarded      OK")


if __name__ == "__main__":
    print("game rules vs board facts:")
    check_board_facts_still_die()
    check_a_law_survives()
    check_a_law_is_still_falsifiable()
    check_keep_refuses_an_untested_claim()
    check_the_agent_facing_split()
    check_the_doc_says_when_to_write()
    check_death_names_the_write_it_just_destroyed()
    print("all green")
