"""Can the rule gate report a green it did not earn?

Phoenix's whole claim is that a check which has never gone red proves nothing. The rule
gate broke that rule in the quietest possible way: `propose()` returned `ok: True`
whenever no solved level was on file, and solved levels only arrive from boards that
`frames.parse` accepts -- which is ONE of the 25 public games. On the other twenty-four,
every rule ever proposed came back green, forever, having been compared against nothing.

Measured in the recorded traces before the fix: 55 vacuous greens on cd82 alone, and not
one red on any non-parsing game.

This check holds the gate to the thing it exists to enforce:

  1. With nothing solved, a verdict must be reported as UNTESTED, not as agreement, and
     must not be truthy -- so agent code that writes `if propose(r)["ok"]` reads "not
     proven", which is the truth.
  2. An untested verdict must not install an accepted rule.
  3. With solved levels on file the gate must still go BOTH ways: green for a rule that
     reproduces them, red for one that does not. A gate that only says no is as useless
     as one that only says yes.

Run: python -m evals.arc.rule_gate_honesty_check
"""

from __future__ import annotations

from evals.arc.rule_gate import RuleGate


def _layout(pads, colours):
    return {"pads": list(pads), "clues": list(colours), "well_formed": True}


def _fail(m: str) -> str:
    return f"FAIL  {m}"


def _ok(m: str) -> str:
    return f"ok    {m}"


def check_untested_is_not_green() -> tuple[bool, list[str]]:
    gate = RuleGate()
    verdict = gate.propose(lambda layout: [(1, (0, 0))])

    out: list[str] = []
    if verdict.get("ok"):
        return False, [_fail("a gate holding no solved levels still answered ok=True")]
    out.append(_ok("with nothing solved, propose() is not truthy"))

    if verdict.get("tested") != 0:
        return False, [_fail(f"tested={verdict.get('tested')!r}, expected 0")]
    out.append(_ok("the verdict reports tested=0 rather than hiding it"))

    if verdict.get("applies") is not False:
        return False, [_fail("applies is not False on a gate that cannot run")]
    out.append(_ok("the verdict reports applies=False"))

    reason = str(verdict.get("reason", ""))
    if "UNTESTED" not in reason or "NOT REFUTED" not in reason:
        return False, [_fail("the reason does not distinguish untested from refuted")]
    out.append(_ok("the reason says plainly this is not a refutation"))

    if gate.accepted is not None:
        return False, [_fail("an untested verdict installed an accepted rule")]
    out.append(_ok("no rule is accepted on evidence that was never examined"))
    return True, out


def check_gate_still_goes_both_ways() -> tuple[bool, list[str]]:
    """A gate that can only refuse is no more honest than one that can only agree."""
    gate = RuleGate()
    # Two solved boards where the answer is "the clue colour goes on the matching pad".
    for level, pads, colours in ((1, [(0, 0), (4, 0)], [7, 3]),
                                 (2, [(0, 0), (4, 0)], [3, 7])):
        layout = _layout(pads, colours)
        order = [(c, p) for c, p in zip(colours, pads)]
        gate.remember(level, layout, order)

    good = lambda layout: [(c, p) for c, p in zip(layout["clues"], layout["pads"])]
    bad = lambda layout: [(c, p) for c, p in zip(layout["clues"], layout["pads"][::-1])]

    out: list[str] = []
    g = gate.propose(good)
    if not g.get("ok"):
        return False, [_fail(f"the correct rule was refused: {g.get('reason')}")]
    if g.get("tested") != 2 or g.get("applies") is not True:
        return False, [_fail(f"a real test reported tested={g.get('tested')} applies={g.get('applies')}")]
    out.append(_ok("a rule reproducing both solved levels passes, tested=2"))

    b = gate.propose(bad)
    if b.get("ok"):
        return False, [_fail("a rule that contradicts the solved levels was accepted")]
    if not b.get("failed"):
        return False, [_fail("a refusal names no failing level, so it teaches nothing")]
    out.append(_ok(f"a contradicting rule is refused, naming level(s) "
                   f"{[f['level'] for f in b['failed']]}"))
    return True, out


def check_prompt_scopes_the_doctrine() -> tuple[bool, list[str]]:
    """The prompt must not tell all 25 games their deliverable is a rule."""
    from pathlib import Path
    src = Path("evals/arc/codeact_agent.py").read_text(encoding="utf-8")
    out: list[str] = []
    if "\nYOUR DELIVERABLE IS A RULE" in src:
        return False, [_fail("the prompt still states the rule doctrine unconditionally")]
    out.append(_ok("the rule doctrine is no longer stated unconditionally"))
    if "ON A PADS-AND-CLUES GAME, YOUR DELIVERABLE IS A RULE" not in src:
        return False, [_fail("the scoped form of the rule doctrine is missing")]
    out.append(_ok("the rule doctrine is scoped to the game shape it describes"))
    if "READ `tested` BEFORE YOU READ `ok`" not in src:
        return False, [_fail("the prompt does not tell the agent to read `tested` first")]
    out.append(_ok("the prompt tells the agent to read `tested` before `ok`"))
    return True, out


def main() -> int:
    checks = (
        ("an untested gate reports untested", check_untested_is_not_green),
        ("a live gate still goes both ways", check_gate_still_goes_both_ways),
        ("the prompt scopes the doctrine", check_prompt_scopes_the_doctrine),
    )
    bad = 0
    for title, fn in checks:
        good, lines = fn()
        print(f"\n== {title}")
        for line in lines:
            print("  " + line)
        if not good:
            bad += 1
    print()
    if bad:
        print(f"{bad} CHECK(S) FAILED")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
