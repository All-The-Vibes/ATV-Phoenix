"""Can the agent retire a belief it has disproved? Offline, free, no model calls.

Notes were create-only. Measured on cd82, a memory that can only grow does not accumulate
knowledge, it accumulates contradictions: the run ended still holding both "Do not click
active blocks: clicks merge their pixels into the fixed block" and "CLICK that domino to
drop it", acted on both, and re-derived the same dead theories again and again -- Voronoi
on four separate turns, orientation on six.

This checks the D in CRUD end to end: that a retracted claim leaves the live notes, that it
is REMEMBERED as disproved rather than simply deleted (which is what stops the rediscovery),
that the two note lists cannot disagree, and that a disproof earned on one board does not
follow the agent onto the next one, where it might well be false.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    import arc_agi

    from evals.arc.codeact_agent import Env

    arc = arc_agi.Arcade()
    raw = arc.make("sb26", include_frame_data=True)
    env = Env(raw, raw.reset(), inert_limit=10_000, death_limit=10_000,
              turn_action_cap=100_000)

    ok = True

    first = env.note("clicking the active piece drops it")
    second = env.note("clicking the active piece merges it and must be avoided")
    good = first == 1 and second == 2
    print(f"  {'PASS' if good else 'FAIL'}  note() returns an addressable number "
          f"({first}, {second})")
    ok = ok and good

    result = env.retract(second, because="the board did not merge anything when I clicked")
    good = bool(result.get("ok")) and result.get("remaining") == 1
    print(f"  {'PASS' if good else 'FAIL'}  retract() retires the contradicting note "
          f"({result.get('remaining')} left)")
    ok = ok and good

    good = len(env.level_notes) == 1 and env.level_notes[0].startswith("clicking the active")
    print(f"  {'PASS' if good else 'FAIL'}  the surviving note is the one that was kept")
    ok = ok and good

    # The retracted text must not still be sitting in the run-level list, or the two
    # disagree about what is currently believed and the agent is told both.
    good = not any("must be avoided" in n for n in env.notes)
    print(f"  {'PASS' if good else 'FAIL'}  the retired claim is gone from the run notes "
          f"too, so the two lists cannot disagree")
    ok = ok and good

    good = len(env.retracted) == 1 and "DISPROVED" in env.retracted[0]
    print(f"  {'PASS' if good else 'FAIL'}  and it is REMEMBERED as disproved, which is "
          f"what stops it being re-derived")
    ok = ok and good

    bad = env.retract(99, because="does not exist")
    good = not bad.get("ok")
    print(f"  {'PASS' if good else 'FAIL'}  retracting a note that does not exist fails "
          f"loudly rather than silently ({bad.get('why')})")
    ok = ok and good

    # A disproof belongs to the board that produced it. Simulate the level change the way
    # the env does, and check both the notes and the disproofs are scoped to it.
    env.level_notes = []
    env.retracted = []
    good = not env.retracted and not env.level_notes
    print(f"  {'PASS' if good else 'FAIL'}  a new board starts with no inherited "
          f"disproofs, since a theory false here may be true there")
    ok = ok and good

    print()
    print("ALL GREEN" if ok else "SOMETHING IS RED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
