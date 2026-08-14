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
import re
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

    def _reads_outcome(node) -> bool:
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        return "gained" in names or "deaths_this_turn" in attrs

    # Any local whose VALUE is derived from the turn outcome. Booking may be driven
    # either by an `if` on those names or by a variable computed from them -- the
    # property is that the result comes from what happened, not from agent diligence,
    # and pinning one syntax would fail an equivalent rewrite of the same behaviour.
    outcome_vars = set()
    for node in ast.walk(play):
        if isinstance(node, ast.Assign) and _reads_outcome(node.value):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    outcome_vars.add(tgt.id)

    outcome_booking = False
    for node in ast.walk(play):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "record" and node not in learn_nodes):
            continue
        for kw in node.keywords:
            if kw.arg == "won" and isinstance(kw.value, ast.Name) \
                    and kw.value.id in outcome_vars:
                outcome_booking = True
    if not outcome_booking:
        for node in ast.walk(play):
            if not isinstance(node, ast.If) or not _reads_outcome(node.test):
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


def check_learn_is_documented_in_the_api_block() -> tuple[bool, str]:
    """`learn()` must be in the SYSTEM API block, with real weight.

    This check exists because the wiring landed and the agent still never called it:
    zero `learn(` calls across 51 turns on cd82, vc33 and tu93. The primitive was in
    the namespace and mentioned in the per-turn message, and absent from the SYSTEM
    API block where the agent learns which tools are real.

    That is Gap 18 exactly -- `note()` got one line next to `mechanic()`'s twenty-four
    and twelve runs called `note()` zero times -- and Gap 10's rule, that an
    undocumented or mis-described primitive is simply never used. `accept()` is the
    standing proof: present in the REPL, absent from every trace ever recorded.

    So the requirement is mechanical rather than aesthetic: `learn(` appears in the
    SYSTEM prompt's API block, and its entry is not a throwaway line next to the
    primitive it competes with for attention.
    """
    import evals.arc.codeact_agent as mod

    system = getattr(mod, "SYSTEM", "")
    if "learn(" not in system:
        return False, (
            "learn( is absent from the SYSTEM prompt. Measured consequence: zero calls "
            "in 51 turns across three games. An undocumented primitive is never used."
        )

    def _entry(name: str) -> int:
        i = system.find(f"{name}(")
        if i < 0:
            return 0
        rest = system[i:]
        # The API block is one indented entry per primitive; the next entry starts at
        # a line whose first non-space run is `word(`. Measure to there.
        lines = rest.splitlines()
        out = [lines[0]]
        for line in lines[1:]:
            stripped = line.strip()
            if stripped and re.match(r"^[a-z_]+\(", stripped) and "->" in line:
                break
            out.append(line)
        return len("\n".join(out))

    learn_len = _entry("learn")
    mech_len = _entry("mechanic")
    if learn_len < 200:
        return False, (
            f"learn()'s API entry is {learn_len} chars against mechanic()'s {mech_len}. "
            f"Gap 18 measured what a starved entry produces: the primitive is not used."
        )
    return True, (
        f"learn() is documented in the API block ({learn_len} chars, "
        f"mechanic() {mech_len})"
    )


def check_the_harness_asks_after_a_level_clear() -> tuple[bool, str]:
    """Documenting `learn()` was necessary and measurably not sufficient.

    With a full API entry in place, r9's cd82/vc33/ft09 read it, cleared levels --
    ft09 reached 4/6 -- and called `learn()` ZERO times across 48 turns. Documentation
    fixed the "does not exist" failure and left a second one untouched.

    The cause is structural, not stylistic: RHAE scores THIS game, and a skill saved
    now pays off on the NEXT one. An agent optimising its own run is behaving correctly
    when it declines. So the harness has to ASK, at the moment the cost is lowest and
    the evidence strongest -- the turn a level actually fell. That is the same mechanism
    the death and stall messages already use, pointed at the positive signal.

    Pinned mechanically: some branch in `play` keyed on a level having just been gained
    must mention `learn(`.
    """
    import evals.arc.codeact_agent as mod

    tree = ast.parse(inspect.getsource(mod))
    play = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "play"), None)
    if play is None:
        return False, "play() is gone; this check is aimed at the wrong function"

    for node in ast.walk(play):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if not (names & {"gained_last_turn", "gained"}):
            continue
        text = " ".join(
            n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        if "learn(" in text:
            return True, "the harness asks for a skill on the turn after a level falls"
    return False, (
        "nothing asks the agent to save its working code after a level clear. Measured: "
        "with learn() fully documented, 48 turns and multiple cleared levels produced "
        "zero calls, because saving a skill pays off on the NEXT game, not this one."
    )


def check_concurrent_saves_do_not_clobber() -> tuple[bool, str]:
    """Two agents writing the library must not destroy each other's skills.

    Measured on r10, and it destroyed real work. Three agents ran concurrently on
    ft09, vc33 and tu93 against one `skills.json`. vc33 saved `read_blob_geometry`
    and `match_embedded_and_loose_connectors` -- both verified present on disk -- and
    a later save from the tu93 process overwrote the file with ITS view of the
    library, taken when it started. Both vc33 skills were gone, permanently, with no
    error anywhere: the agent was told `{"ok": True}`, the write succeeded, and the
    skill evaporated minutes later.

    `save()` serialises the whole in-memory dict, and every process loads once at
    startup, so the last writer wins and silently discards everything learned since.
    A skill library that loses skills under exactly the condition it is used in --
    a parallel wave -- compounds nothing, which is the entire point of having one.

    The fix is to merge against what is on disk at write time rather than trusting a
    snapshot from process start. This check simulates the race directly.
    """
    tmp = Path(tempfile.mkdtemp()) / "skills.json"
    a = SkillLibrary(path=tmp)
    a.add("from_a", "vc33", "def from_a():\n    return 'a'\n", "A's skill",
          tags=["general"])

    # B starts here, so its in-memory view already contains from_a.
    b = SkillLibrary(path=tmp)
    # A learns something else AFTER B loaded -- the race window.
    a.add("from_a_late", "vc33", "def from_a_late():\n    return 'a2'\n", "A's second",
          tags=["general"])
    # Now B writes. Under a whole-file overwrite this erases from_a_late.
    b.add("from_b", "tu93", "def from_b():\n    return 'b'\n", "B's skill",
          tags=["general"])

    on_disk = {s.name for s in SkillLibrary(path=tmp).skills.values()}
    lost = {"from_a", "from_a_late", "from_b"} - on_disk
    if lost:
        return False, (
            f"a concurrent save destroyed {sorted(lost)}. Every parallel wave silently "
            f"loses skills, and the agent is told the write succeeded."
        )
    return True, "concurrent saves merge; no skill is lost to another process's write"


def check_concurrent_results_survive() -> tuple[bool, str]:
    """A win booked by one process must not be reverted by another's save."""
    tmp = Path(tempfile.mkdtemp()) / "skills.json"
    a = SkillLibrary(path=tmp)
    a.add("shared", "vc33", "def shared():\n    return 1\n", "Shared skill",
          tags=["general"])

    b = SkillLibrary(path=tmp)          # B's view: shared at 0W/0L
    a.record("shared", won=True)        # A books a win
    a.record("shared", won=True)
    b.record("shared", won=False)       # B writes from its stale view

    got = SkillLibrary(path=tmp).skills["shared"]
    if got.wins < 2:
        return False, (
            f"wins were rolled back by a concurrent write: expected >=2W, got "
            f"{got.wins}W/{got.losses}L. Transfer is gated on wins > 0, so losing "
            f"them silently keeps the library from ever compounding."
        )
    return True, f"results survive a concurrent write ({got.wins}W/{got.losses}L)"


def check_credit_spans_the_level_not_the_turn() -> tuple[bool, str]:
    """A skill used while solving a level must be credited when that level falls.

    The first version booked a win only when the skill's name appeared in the code of
    the very turn that cleared. Measured on r10, that credited nothing: ft09 went 6/6
    and tu93 reached 5/9, both re-used skills they had written, and NO level-clearing
    turn happened to call one -- so every transferable skill stayed at 0W/0L and
    transfer, which is gated on `wins > 0`, could never unlock.

    That is the wrong unit. A perception skill earns its keep by being called on the
    turn that UNDERSTANDS the board; the clear often lands a turn or two later. Credit
    therefore has to span the level, not the turn: every skill called since the last
    level boundary is credited when the level falls.

    Pinned by requiring `play` to keep a per-level record of which skills were called,
    reset at the level boundary, rather than reading only the current turn's code.
    """
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod.play)
    if "skills_used_this_level" not in src:
        return False, (
            "credit is still scoped to a single turn's code. Measured on r10: two games "
            "improved while re-using their own skills and not one win was booked, "
            "because the clearing turn did not happen to name the skill."
        )
    tree = ast.parse(inspect.getsource(mod))
    play = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "play"), None)
    cleared = False
    for node in ast.walk(play):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "skills_used_this_level":
                    if isinstance(node.value, (ast.Set, ast.Call, ast.Dict)):
                        cleared = True
    if not cleared:
        return False, "skills_used_this_level is never reset; credit would leak across levels"
    return True, "skills called anywhere on a level are credited when that level falls"


def check_credit_is_symmetric_per_level() -> tuple[bool, str]:
    """A level can be cleared once but died on twenty-three times.

    Level-scoped credit fixed the wins that were never booked and created the mirror
    defect. A clear fires at most ONCE per level, while a death fires on every attempt,
    so losses accumulate roughly an order of magnitude faster than wins on exactly the
    games that are hard. Measured on the live library after r11: 6 wins against 33
    losses, `small_object_locator` at 0W/23L on bp35 and `read_rolling_token` at 0W/7L
    on sc25 -- and `Skill.retired` fires at four results below a third, so both are
    already retired.

    Both are PERCEPTION skills. Reading the board is not what killed the agent
    twenty-three times, and the library has now thrown away its best material from the
    two hardest games. Worse, no transferable skill anywhere holds a single win, and
    transfer is gated on `wins > 0` -- so the scoring asymmetry alone keeps the library
    from ever compounding.

    The fix is one result per level per skill: a skill gets at most one win or one loss
    for the level it was used on, whichever the level ended in.
    """
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod.play)
    if "scored_this_level" not in src:
        return False, (
            "a skill can be charged once per DEATH but credited only once per LEVEL. "
            "Measured after r11: 6 wins against 33 losses, two perception skills "
            "retired at 0W/23L and 0W/7L, and not one transferable skill holding a win "
            "-- so transfer, gated on wins > 0, can never unlock."
        )

    # Checked as the actual set difference, not as the name appearing: a mutation that
    # dropped `- scored_this_level` from the booking left an earlier version of this
    # check green, because the variable is still declared and still reset elsewhere.
    tree = ast.parse(src)
    subtracts = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
                and isinstance(node.right, ast.Name)
                and node.right.id == "scored_this_level"):
            subtracts = True
            break
    if not subtracts:
        return False, (
            "the booking does not exclude skills already scored on this level, so a "
            "skill is charged again on every death. That is the asymmetry that produced "
            "6 wins against 33 losses and retired two perception primitives."
        )

    # And the exclusion must be maintained -- a difference that is never added back to
    # would exclude nothing on the second death.
    marks = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "scored_this_level":
                marks = True
    if not marks:
        return False, "scored_this_level is never added to, so the exclusion is empty"
    return True, "a skill takes at most one result per level, so credit is symmetric"


CHECKS = [
    ("the playing agent is wired to the library", check_agent_calls_the_library),
    ("learn() is documented where tools are declared",
     check_learn_is_documented_in_the_api_block),
    ("the harness asks after a level clear",
     check_the_harness_asks_after_a_level_clear),
    ("credit spans the level, not the turn",
     check_credit_spans_the_level_not_the_turn),
    ("credit is symmetric per level", check_credit_is_symmetric_per_level),
    ("a won skill transfers to a new game", check_a_winning_skill_transfers),
    ("only GENERAL skills cross games", check_only_general_skills_transfer),
    ("an installed skill is callable", check_install_makes_it_callable),
    ("wins and losses are booked durably", check_results_are_booked),
    ("concurrent saves do not clobber", check_concurrent_saves_do_not_clobber),
    ("concurrent results survive", check_concurrent_results_survive),
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
