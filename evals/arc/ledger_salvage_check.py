"""Gap 11: a death must not destroy the lesson the death taught.

`Died` aborts the agent's cell where it stands, so every statement after the dying
action is skipped -- including the `mechanic()` call that recorded what killed it.
Measured across 41 traces on disk: 96 ledger writes sat after an action on a turn
that died, and every one was lost. `bp35-b` called `mechanic()` seventeen times and
finished with an empty mechanics list.

This pins the recovery three ways: the fix is present in the source, a simulated
death mid-cell keeps the write, and the replay refuses to touch the board or to
record the same line twice.

Free. No API calls, no game, no spend.
"""
import ast
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evals.arc.codeact_agent import LEDGER_METHODS, _salvage_ledger  # noqa: E402


class FakeEnv:
    """The smallest thing that can be written to and can die."""

    def __init__(self):
        self.mechanics_learned = []
        self.notes = []
        self.level_notes = []
        self.retracted = []
        self._ledger_lines = set()
        self.board_reads = 0

    def _mark_ledger(self):
        self._ledger_lines.add(sys._getframe(2).f_lineno)

    def mechanic(self, text, claim=None):
        entry = str(text)[:200]
        if entry in self.mechanics_learned:
            return {"ok": False, "why": "already recorded"}
        self._mark_ledger()
        self.mechanics_learned.append(entry)
        return {"ok": True, "n": len(self.mechanics_learned)}

    def note(self, text):
        self._mark_ledger()
        self.level_notes.append(str(text)[:200])
        return len(self.level_notes)

    # -- board surface: must never be reached by a salvage --
    def grid(self):
        self.board_reads += 1
        return [[0]]

    def action1(self):
        raise RuntimeError("YOU DIED")


def run_cell(env, code):
    """Execute a cell the way the agent's turn loop does, then salvage."""
    ns = {"env": env}
    env._ledger_lines = set()
    try:
        exec(compile(code, "<cell>", "exec"), ns)  # noqa: S102
        died = False
    except RuntimeError:
        died = True
    saved = _salvage_ledger(code, ns, env) if died else 0
    return died, saved


def check_source_shape():
    """The three abort paths must each call the salvage."""
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod)
    tree = ast.parse(src)

    handlers = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        names = [n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)]
        calls = {c.func.id for c in ast.walk(node)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        for name in names:
            if name in {"Died", "LevelCleared", "StallDetected"}:
                handlers[name] = handlers.get(name, False) or ("_salvage_ledger" in calls)

    missing = [k for k in ("Died", "LevelCleared", "StallDetected") if not handlers.get(k)]
    if missing:
        return False, f"these abort paths do not salvage the ledger: {', '.join(missing)}"
    if "grid" in LEDGER_METHODS or "action1" in LEDGER_METHODS:
        return False, "LEDGER_METHODS admits a board call; a salvage could act on a pristine board"
    return True, f"all three abort paths salvage; LEDGER_METHODS = {sorted(LEDGER_METHODS)}"


def check_write_survives_death():
    """The write the cell never reached is recorded anyway."""
    env = FakeEnv()
    code = (
        "reason = 'row 63 drains one cell per drop'\n"
        "env.note('about to test the bar')\n"
        "env.action1()\n"
        "env.mechanic(f'CONFIRMED: {reason}')\n"
    )
    died, saved = run_cell(env, code)
    if not died:
        return False, "the cell did not die; the fixture is wrong"
    if saved != 1:
        return False, f"expected 1 salvaged write, got {saved}"
    if env.mechanics_learned != ["CONFIRMED: row 63 drains one cell per drop"]:
        return False, f"the computed text did not survive: {env.mechanics_learned}"
    if env.level_notes != ["about to test the bar"]:
        return False, f"the pre-death note was disturbed: {env.level_notes}"
    return True, "the unreached write was recovered with its computed text intact"


def check_no_double_record():
    """A write that already ran is not replayed."""
    env = FakeEnv()
    code = (
        "env.note('this one ran')\n"
        "env.action1()\n"
        "env.note('this one did not')\n"
    )
    died, saved = run_cell(env, code)
    if not died:
        return False, "the cell did not die; the fixture is wrong"
    if env.level_notes != ["this one ran", "this one did not"]:
        return False, f"expected exactly one of each, got {env.level_notes}"
    if saved != 1:
        return False, f"expected 1 salvaged write, got {saved}"
    return True, "the executed write was not replayed; only the unreached one was"


def check_board_is_never_touched():
    """A statement that reads the board is left alone, however it is written."""
    env = FakeEnv()
    code = (
        "env.action1()\n"
        "env.mechanic(f'the board is {env.grid()}')\n"
        "env.note('safe')\n"
    )
    died, saved = run_cell(env, code)
    if not died:
        return False, "the cell did not die; the fixture is wrong"
    if env.board_reads:
        return False, f"a salvage read the pristine board {env.board_reads} time(s)"
    if env.mechanics_learned:
        return False, f"a board-dependent write was replayed: {env.mechanics_learned}"
    if env.level_notes != ["safe"]:
        return False, f"the board-free write was not salvaged: {env.level_notes}"
    if saved != 1:
        return False, f"expected 1 salvaged write, got {saved}"
    return True, "the board-reading write was skipped; the board-free one was kept"


def check_salvage_never_raises():
    """A cell that cannot be replayed costs nothing."""
    env = FakeEnv()
    code = "env.action1()\nenv.note(undefined_name)\n"
    died, saved = run_cell(env, code)
    if not died:
        return False, "the cell did not die; the fixture is wrong"
    if saved != 0:
        return False, f"a broken statement reported {saved} saved"
    return True, "an unreplayable write failed quietly instead of ending the run"


CHECKS = [
    ("fix is present in the source", check_source_shape),
    ("the write a death destroys survives", check_write_survives_death),
    ("no write is recorded twice", check_no_double_record),
    ("no salvage touches the board", check_board_is_never_touched),
    ("a failed salvage costs nothing", check_salvage_never_raises),
]


def main():
    failures = 0
    for title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # a check that crashes is a check that failed
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {title}\n       {detail}")
        failures += not ok
    print("-" * 70)
    print("ledger salvage: ALL PASS" if not failures else f"ledger salvage: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
