"""Measure what a death actually costs the ledger.

The handoff says "buffer ledger writes and flush before the raise". That reads as
though the writes exist and are dropped. They are not. `mechanic()` appends to a
list the moment it is called, and the call is never reached: `Died` propagates out
of the agent's cell and every statement after the dying action is skipped.

So the question that decides the fix is not "where do we flush" but "can the write
be known before the cell runs". A call with a literal string argument can. A call
whose argument is computed cannot. This measures the split across every trace on
disk, because a fix that recovers a fifth of the losses is not worth its surface.
"""
import ast
import glob
import json
import os
import sys

ACTION_NAMES = {
    "action1", "action2", "action3", "action4", "action5", "action6", "action7",
    "act", "click", "submit", "drop", "press",
}
LEDGER_NAMES = {"mechanic", "note", "retract", "unmechanic", "accept", "keep"}


def _attr_name(node):
    """`env.mechanic(...)` -> 'mechanic'. Anything else -> None."""
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _all_calls(tree):
    """Every call in source order, with the name it invokes."""
    out = []
    for node in ast.walk(tree):
        name = _attr_name(node)
        if name:
            out.append((getattr(node, "lineno", 0), getattr(node, "col_offset", 0), name, node))
    out.sort(key=lambda r: (r[0], r[1]))
    return out


def _is_literal(node):
    """Are every one of this call's arguments knowable without running the cell?"""
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        try:
            ast.literal_eval(arg)
        except (ValueError, SyntaxError, TypeError):
            return False
    return True


def measure(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    stats = {
        "turns": len(rows),
        "died_turns": 0,
        "ledger_calls": 0,
        "ledger_after_action": 0,
        "at_risk": 0,           # after an action, on a turn that died
        "at_risk_literal": 0,   # ... and recoverable by a pre-scan
        "at_risk_computed": 0,  # ... and not
    }

    for row in rows:
        code = row.get("code") or ""
        output = json.dumps(row.get("output") or "")
        died = "YOU DIED" in output
        if died:
            stats["died_turns"] += 1
        if not code.strip():
            continue
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue

        calls = _all_calls(tree)
        seen_action = False
        for _, _, name, node in calls:
            if name in ACTION_NAMES:
                seen_action = True
                continue
            if name not in LEDGER_NAMES:
                continue
            stats["ledger_calls"] += 1
            if not seen_action:
                continue
            stats["ledger_after_action"] += 1
            if died:
                stats["at_risk"] += 1
                if _is_literal(node):
                    stats["at_risk_literal"] += 1
                else:
                    stats["at_risk_computed"] += 1
    return stats


def main(argv):
    paths = argv[1:] or sorted(glob.glob(os.path.join("eval", "arc-results", "trace-*.jsonl")))
    if not paths:
        print("no traces found")
        return 1

    total = {}
    print(f"{'trace':<26}{'turns':>6}{'died':>6}{'ledger':>8}{'post-act':>10}"
          f"{'at-risk':>9}{'literal':>9}{'computed':>10}")
    print("-" * 84)
    for path in paths:
        s = measure(path)
        if not s["ledger_calls"]:
            continue
        for k, v in s.items():
            total[k] = total.get(k, 0) + v
        print(f"{os.path.basename(path):<26}{s['turns']:>6}{s['died_turns']:>6}"
              f"{s['ledger_calls']:>8}{s['ledger_after_action']:>10}"
              f"{s['at_risk']:>9}{s['at_risk_literal']:>9}{s['at_risk_computed']:>10}")

    print("-" * 84)
    print(f"{'TOTAL':<26}{total.get('turns',0):>6}{total.get('died_turns',0):>6}"
          f"{total.get('ledger_calls',0):>8}{total.get('ledger_after_action',0):>10}"
          f"{total.get('at_risk',0):>9}{total.get('at_risk_literal',0):>9}"
          f"{total.get('at_risk_computed',0):>10}")

    at_risk = total.get("at_risk", 0)
    if at_risk:
        lit = total.get("at_risk_literal", 0)
        print(f"\na pre-scan of literal arguments would recover {lit}/{at_risk} "
              f"({100.0 * lit / at_risk:.0f}%) of the writes a death destroys")
    else:
        print("\nno ledger write on disk was ever lost to a death")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
