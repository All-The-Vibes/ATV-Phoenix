"""Does the harness ever look at its failures TOGETHER?

ARC Prize's own analysis of frontier models on this benchmark names the dominant
failure mode "True Local Effect, False World Model": the model perceives a real local
effect and cannot anchor it in a global rule. bp35 is our instance of it and the only
game still at zero levels. Across three waves it produced three DIFFERENT theories of
the same game -- a click/clear theory in r6, a platform/steering theory in r7 -- each
internally coherent, each built from one run's evidence, none of them the game.

The harness already reacts to failure, and it reacts one failure at a time: after a
death it asks which single belief was wrong. That is Reflexion's shape, and ExpeL
(AAAI 2024 Oral, arXiv:2308.10144) measured that it is the weaker half. Their result
is that per-episode reflection plus a SECOND step -- batching many trajectories into
one call that extracts the invariant across all of them -- beats reflection alone
(ALFWorld 0.80 vs 0.71). We had the first step and not the second.

A single death teaches "that was wrong". Twenty deaths, read together, teach what the
game is: if the agent dies at 12 actions, then 41, then 64, that is a budget. If it
dies wherever colour 9 arrives, that is a hazard. Neither is visible one death at a
time, which is the only way this harness has ever presented them.

These checks pin the batching, not the wording:
  - the harness keeps a durable record of failures, not just a count
  - it asks for ONE rule covering ALL of them, on a schedule, not per death
  - the ask carries the actual evidence, since a synthesis prompt with no data is a
    request for a guess
  - it never fires before there is enough evidence to generalise from

Free. No API calls, no game, no spend.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _play_source() -> str:
    import evals.arc.codeact_agent as mod
    return inspect.getsource(mod.play)


def check_failures_are_recorded() -> tuple[bool, str]:
    """A count cannot be synthesised over. The failures themselves must persist.

    Checked as an actual append rather than as the name appearing somewhere: a
    mutation test that renamed only the append target left this green, because the
    attribute is still declared in `Env.__init__` and still read in `play`. A record
    nothing writes to is exactly the empty-ledger failure this is meant to fix.
    """
    import evals.arc.codeact_agent as mod

    src = inspect.getsource(mod)
    if "death_log" not in src:
        return False, (
            "nothing accumulates the individual failures. `env.deaths` is an integer, "
            "and an integer cannot be read for a pattern -- which is why every death "
            "has only ever been able to teach 'that was wrong'."
        )
    env_src = inspect.getsource(mod.Env)
    if "death_log" not in env_src:
        return False, "the failure record is not owned by Env, so it dies with the turn"

    appended = False
    for node in ast.walk(ast.parse(env_src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("append", "extend")
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "death_log"):
            appended = True
            break
    if not appended:
        return False, (
            "death_log is declared but never appended to. An empty record synthesises "
            "to nothing, and the ask would fire over no evidence at all."
        )
    return True, "individual failures are appended to a durable record, not just counted"


def _batch_ask_fstrings(src: str):
    """Every f-string in `play` that reads like an ask over MANY failures at once.

    Matched on what the message MUST contain to be that ask -- the failure count and
    language about all of them together -- rather than on the word "synthesis". The
    agent-facing text deliberately avoids jargon, and a check that demanded the jargon
    would force the prose to name a mechanism the agent does not need named.
    """
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ).upper()
        together = any(k in text for k in ("TOGETHER", "ALL OF THESE", "ALL OF THEM"))
        one_rule = any(k in text for k in ("SINGLE RULE", "ONE RULE", "ONE QUESTION"))
        if together and one_rule:
            out.append(node)
    return out


def check_a_batch_synthesis_is_requested() -> tuple[bool, str]:
    """The ask must be for ONE rule over MANY failures, and must be periodic."""
    src = _play_source()
    if not _batch_ask_fstrings(src):
        return False, (
            "the harness never asks the agent to read its failures together and name the "
            "one rule behind all of them. It asks, after each death, which belief was "
            "wrong -- Reflexion's shape, which ExpeL measured as the weaker half "
            "(ALFWorld 0.71 vs 0.80 with batch rule extraction)."
        )
    tree = ast.parse(src)
    periodic = any(
        isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod) for n in ast.walk(tree)
    )
    if not periodic:
        return False, (
            "the ask is not on a schedule. Firing on every death is per-death reflection "
            "again; firing once is a single shot at the hardest question in the run."
        )
    return True, "a periodic batch ask across accumulated failures is present"


def check_the_ask_carries_the_evidence() -> tuple[bool, str]:
    """A synthesis prompt with no data attached is a request for a guess."""
    for node in _batch_ask_fstrings(_play_source()):
        if any(isinstance(v, ast.FormattedValue) for v in node.values):
            return True, "the batch ask interpolates the accumulated failure record"
    return False, (
        "the batch ask carries no interpolated evidence. Asking for the invariant behind "
        "failures the agent cannot see is asking it to guess."
    )


def check_it_waits_for_enough_evidence() -> tuple[bool, str]:
    """One or two failures is not a pattern; a rule drawn from them is noise."""
    src = _play_source()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        names = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        if "death_log" not in names and "deaths" not in names:
            continue
        for comp in node.comparators:
            if isinstance(comp, ast.Constant) and isinstance(comp.value, int):
                if comp.value >= 3:
                    return True, (
                        f"synthesis waits for at least {comp.value} failures before "
                        f"generalising"
                    )
    return False, (
        "no minimum-evidence gate found. A rule synthesised from one death is the same "
        "over-generalisation from a single observation this is meant to fix."
    )


CHECKS = [
    ("failures are recorded, not just counted", check_failures_are_recorded),
    ("a batch synthesis is requested periodically", check_a_batch_synthesis_is_requested),
    ("the ask carries the actual evidence", check_the_ask_carries_the_evidence),
    ("it waits for enough evidence", check_it_waits_for_enough_evidence),
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
    print("failure synthesis: ALL PASS" if not failures
          else f"failure synthesis: {failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
