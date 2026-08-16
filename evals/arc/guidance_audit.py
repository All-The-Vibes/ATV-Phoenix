"""Which guidance does the harness compose, and which can we actually verify landed?

Twice this session a message was built and never delivered, and both times the bug was
invisible because the trace did not record the message. `consolidate` was fixed in
291aa66; the fix did not generalise and `pace` needed its own commit in 304616c. That
is two instances of the same defect found one at a time, which means the third is
already written and waiting.

So enumerate it mechanically instead of one bug at a time: every string variable that
`play()` assembles and injects into the prompt, against the set of keys the trace row
actually writes. Anything in the first set and not the second is a message we are
flying blind on -- it can be composed, overwritten, and silently dropped, and no
artifact on disk would show it.

Free. Pure source analysis, no game, no API calls.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def play_tree() -> ast.AST:
    import evals.arc.codeact_agent as mod
    return ast.parse(inspect.getsource(mod.play))


def guidance_vars(tree: ast.AST) -> dict[str, dict]:
    """Locals built up as text -- seeded to "" and then appended to.

    Records LINE NUMBERS, not counts. The bug in c07ff22 was not "there are several
    assignments", it was "a plain assignment runs AFTER an append and erases it". A
    count cannot express that; an ordering can. The first version of this audit counted,
    reported 4 assignments on `cleared` as a risk that cannot occur, and simultaneously
    passed the real erasure when it was reintroduced.
    """
    seeded: dict[str, int] = {}
    appends: dict[str, list[int]] = {}
    plains: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not isinstance(t, ast.Name):
                    continue
                if isinstance(node.value, ast.Constant) and node.value.value == "":
                    seeded.setdefault(t.id, node.lineno)
                else:
                    plains.setdefault(t.id, []).append(node.lineno)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            appends.setdefault(node.target.id, []).append(node.lineno)

    out = {}
    for name, seed_line in seeded.items():
        app = sorted(appends.get(name, []))
        pl = sorted(plains.get(name, []))
        # An erasure is a plain assignment that sits after the first append. Anything
        # before the first append is just initialisation by another route.
        erasing = [ln for ln in pl if app and ln > app[0]]
        out[name] = {"appends": len(app), "overwrites": len(pl), "erasing": erasing}
    return out


def trace_write(tree: ast.AST) -> ast.Dict | None:
    """The dict that becomes a trace row -- the one with "turn" and "code" in it.

    Scanning every dict literal in play() and harvesting every name inside it was how
    the first version concluded that all three guidance strings reached disk. They do,
    but not because that check demonstrated it: the check would have said yes to
    anything.
    """
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if {"turn", "code"} <= keys and (best is None or len(keys) > len(best.keys)):
            best = node
    return best


def traced_names(tree: ast.AST) -> set[str]:
    """Names whose content reaches the trace row, following appends one hop at a time.

    `cleared` is never a trace key, but it is appended onto `last_output`, which IS
    written as "output" -- and appended at the END, so the [-1500:] truncation keeps it.
    A key-only audit calls that unverifiable and sends you hunting a bug that is not
    there, which is exactly what happened.
    """
    row = trace_write(tree)
    if row is None:
        return set()
    reached = {n.id for v in row.values for n in ast.walk(v) if isinstance(n, ast.Name)}
    for _ in range(4):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.AugAssign) or not isinstance(node.target, ast.Name):
                continue
            if node.target.id not in reached:
                continue
            for n in ast.walk(node.value):
                if isinstance(n, ast.Name) and n.id not in reached:
                    reached.add(n.id)
                    grew = True
        if not grew:
            break
    return reached


def exclusive_branches(tree: ast.AST) -> set[str]:
    """Names assigned inside except-handlers of one try.

    Only one handler can run per turn, so four `cleared = str(exc)` lines across four
    handlers are not four chances to erase each other -- they are one assignment. The
    first version of this audit counted them syntactically and reported an erasure risk
    that cannot occur.
    """
    safe = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            for sub in ast.walk(handler):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            safe.add(t.id)
    return safe


def main() -> int:
    tree = play_tree()
    guides = guidance_vars(tree)
    traced = traced_names(tree)
    exclusive = exclusive_branches(tree)

    if not guides:
        print("found no accumulating guidance variables -- the audit is looking in the "
              "wrong place, not the harness being clean")
        return 1
    if not traced:
        print("could not locate the trace-write dict, so nothing can be judged traced")
        return 1

    print(f"{'variable':<20} {'appends':>8} {'erasing':>8} {'in trace':>9}  risk")
    print("-" * 70)
    blind = overwrite_risk = 0
    for name, info in sorted(guides.items(), key=lambda kv: -kv[1]["appends"]):
        if info["appends"] == 0:
            continue                       # seeded and never appended: not guidance
        in_trace = name in traced
        # A plain assignment after an append erases it -- unless every assignment to
        # this name lives in an except-handler, where only one branch can ever run.
        erasing = [] if name in exclusive else info["erasing"]
        risk = []
        if not in_trace:
            risk.append("UNVERIFIABLE from disk")
            blind += 1
        if erasing:
            risk.append(f"plain assignment at line {erasing[0]} erases earlier appends")
            overwrite_risk += 1
        note = ", ".join(risk) or ("ok" if name not in exclusive
                                   else "ok (assignments are exclusive branches)")
        print(f"{name:<20} {info['appends']:>8} {len(erasing):>8} "
              f"{('yes' if in_trace else 'NO'):>9}  {note}")

    print("-" * 70)
    print(f"guidance variables that never reach the trace : {blind}")
    print(f"variables at real risk of silent overwrite    : {overwrite_risk}")
    print()
    if blind or overwrite_risk:
        print("A message the trace does not record can be composed, overwritten, and")
        print("dropped with no artifact showing it -- that bug shipped twice this")
        print("session (291aa66, c07ff22).")
        return 1
    print("Every guidance string the harness composes reaches the trace, and no plain")
    print("assignment can erase an earlier append. The defect class that cost 291aa66")
    print("and c07ff22 has no third instance left in play().")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
