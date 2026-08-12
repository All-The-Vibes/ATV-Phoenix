"""A budget wide enough to brute-force with will be brute-forced with.

`turn_action_cap` was 120. Runs that clear 6-8 levels spend 7-10 actions per turn,
so 120 constrained nobody -- it was twelve times what a winning turn has ever
needed, and what it licensed was batch search.

Measured on sb26, a 7-pad board with 7! = 5,040 candidate assignments: one model
reached turn 11 holding a TRIED set of thirteen permutations and queued six more in
that single turn, spending 48 actions. It ended 3/8 in 303 actions. The model that
cleared that same level did it in 26, by reasoning about the clue order. Corpus-wide,
62% of every action ever spent came AFTER the run's last cleared level -- that is
what searching a refused space costs, and RHAE squares it.

So the cap tightens as the level resists: full while progress is happening, 25 after
six turns, 12 after twelve. That is the opposite of what a searcher wants and exactly
what a reasoner needs, because when the board keeps refusing you the next thing to
change is the idea, and ideas are free.

Free. No API calls, no game, no spend.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evals.arc.codeact_agent import Env, TurnBudgetExhausted  # noqa: E402


def _env(cap=120):
    """An Env with the real budget logic and nothing else wired up."""
    e = Env.__new__(Env)
    e._turn_action_cap = cap
    e._turn_spent = 0
    e._turns_on_level = 0
    return e


def check_fresh_level_gets_the_full_budget():
    e = _env()
    if e.turn_budget() != 120:
        return False, f"a fresh level offered {e.turn_budget()}, expected the full 120"
    e._turns_on_level = 5
    if e.turn_budget() != 120:
        return False, f"still-progressing level narrowed early to {e.turn_budget()}"
    return True, "a level that has not resisted keeps the full budget through turn 5"


def check_budget_narrows_as_the_level_resists():
    e = _env()
    seen = {}
    for turns in (6, 11, 12, 30):
        e._turns_on_level = turns
        e._turn_spent = 0
        seen[turns] = e.turn_budget()
    if seen[6] != 25 or seen[11] != 25:
        return False, f"turns 6-11 offered {seen[6]}/{seen[11]}, expected 25"
    if seen[12] != 12 or seen[30] != 12:
        return False, f"turns 12+ offered {seen[12]}/{seen[30]}, expected 12"
    return True, f"budget goes 120 -> 25 at turn 6 -> 12 at turn 12 (measured: {seen})"


def check_the_cap_is_enforced_not_advertised():
    """`_step` must read the same live number the prompt shows."""
    e = _env()
    e._turns_on_level = 20          # deep stall: cap is 12
    e._turn_spent = 12
    try:
        e._step(1)
    except TurnBudgetExhausted as exc:
        msg = str(exc)
        if "12" not in msg:
            return False, "the refusal does not tell the agent what the live cap is"
        if "IDEA" not in msg and "idea" not in msg:
            return False, "the refusal does not point at changing the idea"
        return True, "_step refuses at the narrowed cap and says why"
    except Exception as exc:
        return False, f"expected TurnBudgetExhausted, got {type(exc).__name__}: {exc}"
    return False, "spending past the narrowed cap was allowed -- the cap is advisory"


def check_a_wide_budget_still_works_when_winning():
    """The fix must not throttle a run that is clearing levels."""
    e = _env()
    e._turns_on_level = 3
    e._turn_spent = 40
    if e.turn_budget() != 80:
        return False, f"a progressing turn offered {e.turn_budget()} after 40 spent, expected 80"
    return True, "a progressing level can still spend well past what a winning turn needs"


def check_level_change_restores_the_budget():
    """A new board has refused nothing yet."""
    import inspect

    src = inspect.getsource(Env._step)
    if "_turns_on_level = 0" not in src:
        return False, "the level transition never resets the stall counter"
    return True, "the counter resets at the level boundary, so a new board starts wide"


CHECKS = [
    ("a fresh level gets the full budget", check_fresh_level_gets_the_full_budget),
    ("the budget narrows as the level resists", check_budget_narrows_as_the_level_resists),
    ("the cap is enforced, not advertised", check_the_cap_is_enforced_not_advertised),
    ("a winning run is not throttled", check_a_wide_budget_still_works_when_winning),
    ("a level change restores the budget", check_level_change_restores_the_budget),
]


def main():
    bad = 0
    for title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {title}\n       {detail}")
        bad += not ok
    print("-" * 74)
    print("turn budget: ALL PASS" if not bad else f"turn budget: {bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
