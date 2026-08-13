"""Does the skill library actually reach the agent that plays?

`skills.py` implements the whole Voyager loop: `install()` execs learned skills into
the REPL namespace, `describe()` offers them in the prompt, `record()` books the
win or the loss, and `available()` gates cross-game transfer on having won somewhere.

`codeact_agent.py` called exactly one method:

    mechanics = SkillLibrary().mechanics_for(game)      # a TEXT blob, same game only

so nothing was ever installed, offered, or scored. `skills.json` is the receipt:
four of its seven skills sit at 0W/0L, not because they failed but because no caller
ever books a result -- and `available()` only transfers a skill once `wins > 0`, so
with wins pinned at zero cross-game transfer could never fire even in principle.
The loop was broken at both ends: nothing went in, nothing came back.

This is the same shape as Gap 10 and as `accept()`: machinery that runs, or in this
case does not even run, while the docs describe a capability the agent never had.

The checks below pin the wiring rather than the intent:
  - the production agent calls install / describe / record, not just mechanics_for
  - a skill that won elsewhere is offered on a NEW game, and one that never won is not
  - installing puts a callable in the namespace
  - a win and a loss both get booked, so `wins > 0` can actually happen
  - a skill whose source is broken cannot take the run down with it

Free. No API calls, no game, no spend.
"""
from __future__ import annotations

import ast
import inspect
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.skills import Skill, SkillLibrary  # noqa: E402


def _fresh() -> SkillLibrary:
    """A library on a throwaway path, so a check never edits the real skills.json."""
    tmp = Path(tempfile.mkdtemp()) / "skills.json"
    return SkillLibrary(path=tmp)


def check_agent_calls_the_library() -> tuple[bool, str]:
    """The playing agent must install, describe and record -- not only read text.

    `record` is checked far more narrowly than the other two, and a mutation test is
    why. An earlier version of this check looked for the NAME anywhere in the module
    and passed even with the automatic scoring deleted, because `learn()` also calls
    `record()` on a skill that fails to install. That is a vacuous gate: it asserted
    "results are booked" while the only surviving caller was the write path.

    So the requirement here is the actual property: a `record()` call inside `play`,
    outside `learn`, in a branch that reads the turn's OUTCOME (`gained` or
    `deaths_this_turn`). Booking driven by what happened, not by the agent choosing to
    be diligent -- which is Gap 10's whole lesson and `accept()`'s standing proof.
    """
    import evals.arc.codeact_agent as mod

    tree = ast.parse(inspect.getsource(mod))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    missing = [m for m in ("install", "describe") if m not in called]
    if missing:
        return False, (
            f"codeact_agent never calls: {', '.join(missing)}. The skill library is "
            f"present but disconnected -- learned skills cannot reach the REPL."
        )

    play = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "play"), None)
    if play is None:
        return False, "play() is gone; this check is aimed at the wrong function"

    # Everything lexically inside the nested `learn` is the WRITE path, not scoring.
    learn_nodes = set()
    for node in ast.walk(play):
        if isinstance(node, ast.FunctionDef) and node.name == "learn":
            learn_nodes = set(ast.walk(node))
            break

    outcome_booking = False
    for node in ast.walk(play):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        reads_outcome = "gained" in names or "deaths_this_turn" in attrs
        if not reads_outcome:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "record" and inner not in learn_nodes):
                outcome_booking = True
                break
        if outcome_booking:
            break

    if not outcome_booking:
        return False, (
            "no record() call in play() is driven by the turn's outcome (gained / "
            "deaths_this_turn) outside learn(). Results would only ever be booked when "
            "the agent writes a skill, so wins stay at 0 and transfer never unlocks."
        )
    return True, "the agent installs skills, offers them, and books the result on outcome"


def check_a_winning_skill_transfers() -> tuple[bool, str]:
    """The generalisation step: a skill that won on game A is offered on game B."""
    lib = _fresh()
    lib.add("read_components", "vc33", "def read_components():\n    return 'ok'\n",
            "Split the board into connected components.", tags=["general"])
    lib.record("read_components", won=True)
    lib.add("solve_vc33", "vc33", "def solve_vc33():\n    return 1\n", "vc33 only.",
            tags=["general"])

    offered = {s.name for s in lib.available("bp35")}
    if "read_components" not in offered:
        return False, ("a skill with a recorded win was NOT offered on a new game; "
                       "cross-game transfer is dead")
    if "solve_vc33" in offered:
        return False, ("a never-won skill leaked to a game it was not learned on; "
                       "transfer must be earned")
    return True, "a won skill transfers to a new game; an unproven one stays home"


def check_install_makes_it_callable() -> tuple[bool, str]:
    """Installing must put a working function in the namespace the agent uses."""
    lib = _fresh()
    lib.add("helper", "bp35", "def helper():\n    return 41 + 1\n", "Answers.")
    ns: dict = {}
    installed = lib.install(ns, "bp35")
    if "helper" not in installed:
        return False, f"install did not report the skill: {installed}"
    if "helper" not in ns:
        return False, "install did not put the skill in the namespace"
    if ns["helper"]() != 42:
        return False, "the installed skill did not execute correctly"
    return True, "an installed skill is callable in the agent's REPL namespace"


def check_results_are_booked() -> tuple[bool, str]:
    """`wins > 0` has to be reachable, or transfer can never unlock."""
    lib = _fresh()
    lib.add("s", "bp35", "def s():\n    return 1\n", "A skill.")
    lib.record("s", won=True)
    lib.record("s", won=False)
    got = lib.skills["s"]
    if (got.wins, got.losses) != (1, 1):
        return False, f"expected 1W/1L, got {got.wins}W/{got.losses}L"
    reread = SkillLibrary(path=lib.path).skills["s"]
    if (reread.wins, reread.losses) != (1, 1):
        return False, "the result did not survive a reload; the library is not durable"
    return True, "wins and losses are booked and persist across a reload"


def check_broken_skill_cannot_kill_the_run() -> tuple[bool, str]:
    """A skill the agent wrote badly must cost the skill, not the run."""
    lib = _fresh()
    lib.add("bad", "bp35", "def bad(:\n    syntax error\n", "Malformed.")
    lib.add("good", "bp35", "def good():\n    return 1\n", "Fine.")
    ns: dict = {}
    try:
        installed = lib.install(ns, "bp35")
    except Exception as exc:
        return False, f"install raised on a broken skill: {type(exc).__name__}: {exc}"
    if "good" not in installed:
        return False, "a broken skill prevented a good one from installing"
    if lib.skills["bad"].losses < 1:
        return False, "the broken skill was not charged a loss"
    return True, "a malformed skill is charged a loss and the good ones still install"


def check_library_is_not_all_solvers() -> tuple[bool, str]:
    """Advisory: report the real library's shape. Never fails the suite.

    A library of per-game solvers (`solve_sb26`) compounds nothing -- `solve_sb26()`
    cannot help on bp35. Voyager's result came from REUSABLE primitives. This does not
    fail, because it measures a judgement call rather than a wiring fact, but it prints
    the number so the split is visible while it is being fixed.
    """
    real = Path(__file__).resolve().parents[2] / "eval" / "arc-results" / "skills.json"
    if not real.exists():
        return True, "(no library on disk yet)"
    try:
        raw = json.loads(real.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, "(library unreadable; not this check's business)"
    skills = [Skill(**e) for e in raw.get("skills", [])]
    solvers = [s for s in skills if s.name.startswith("solve_")]
    unscored = [s for s in skills if s.wins + s.losses == 0]
    return True, (
        f"{len(skills)} skills: {len(solvers)} are per-game solvers, "
        f"{len(unscored)} have never been scored either way"
    )


def check_only_general_skills_transfer() -> tuple[bool, str]:
    """A game-specific SOLVER must not be offered on a different game.

    Wiring transfer on `wins > 0` alone is not safe, and the real library proves it.
    `sp80_generic` won on sp80, is tagged "deadly", and its body is
    `for i in range(5000): press(random.choice([1,2,2,3,4,6]))`. Offering that on bp35
    does not transfer a lesson -- it hands the agent a random-input loop that spends
    the action budget RHAE squares against it and walks into every hazard on the board.
    `solve_vc33_level` is the same shape: it presses action 6 against a board it was
    never written for.

    Winning on game A is evidence a skill is CORRECT, never evidence it is GENERAL.
    Transfer must be earned by being reusable -- a board reader, a component splitter --
    which is what Voyager's result actually rests on.
    """
    lib = _fresh()
    lib.add("solve_vc33_level", "vc33", "def solve_vc33_level():\n    return 1\n",
            "Solves vc33.")
    lib.record("solve_vc33_level", won=True)
    lib.add("read_components", "vc33",
            "def read_components():\n    return []\n",
            "Split any board into connected components.", tags=["general"])
    lib.record("read_components", won=True)

    offered = {s.name for s in lib.available("bp35")}
    if "solve_vc33_level" in offered:
        return False, (
            "a game-specific solver was offered on a game it was never written for. "
            "It cannot help there and it spends actions -- RHAE squares every one."
        )
    if "read_components" not in offered:
        return False, "a general, winning skill was NOT offered on a new game"
    if {s.name for s in lib.available("vc33")} < {"solve_vc33_level", "read_components"}:
        return False, "a skill stopped being offered on its OWN game"
    return True, "only general skills cross games; solvers stay on the game they solve"


CHECKS = [
    ("the playing agent is wired to the library", check_agent_calls_the_library),
    ("a won skill transfers to a new game", check_a_winning_skill_transfers),
    ("only GENERAL skills cross games", check_only_general_skills_transfer),
    ("an installed skill is callable", check_install_makes_it_callable),
    ("wins and losses are booked durably", check_results_are_booked),
    ("a broken skill cannot kill the run", check_broken_skill_cannot_kill_the_run),
    ("library shape (advisory)", check_library_is_not_all_solvers),
]


def main() -> int:
    failures = 0
    for title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # a check that crashes is a check that failed
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {title}\n       {detail}")
        failures += not ok
    print("-" * 70)
    print("skill loop: ALL PASS" if not failures else f"skill loop: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
