"""Recover skills that a concurrent save destroyed, from the traces that recorded them.

Every `learn()` call the agent ever made is in its trace, with the full source it
passed. So a skill lost to the r10 race is not gone -- it is just not in the library
any more, and the library is the only place it was ever load-bearing.

This reads traces, extracts each `learn(...)` call by parsing the turn's code rather
than by regex over it, and re-adds anything the library is currently missing. The
merging `save()` makes that safe to run repeatedly: a name already present is left
alone, including its win/loss record.

Run:  python evals/arc/recover_skills.py            # report only
      python evals/arc/recover_skills.py --apply    # write them back
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.arc.skills import SkillLibrary  # noqa: E402

RESULTS = ROOT / "eval" / "arc-results"


def _literal(node):
    """A constant argument, or None when the agent built it dynamically."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def learn_calls(code: str):
    """Every learn(...) in one turn's code, as (name, source, description, tags).

    Parsed rather than regexed: the source argument is routinely a triple-quoted
    block containing its own parentheses, quotes and `def` lines, and no regex over
    that is worth trusting with the only surviving copy of a skill.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "learn"):
            continue
        args = [_literal(a) for a in node.args]
        kwargs = {k.arg: _literal(k.value) for k in node.keywords if k.arg}
        name = kwargs.get("name") or (args[0] if len(args) > 0 else None)
        source = kwargs.get("source") or (args[1] if len(args) > 1 else None)
        desc = kwargs.get("description") or (args[2] if len(args) > 2 else "")
        tags = kwargs.get("tags") or (args[3] if len(args) > 3 else [])
        if not isinstance(name, str) or not isinstance(source, str):
            continue  # built at runtime; nothing static to recover
        out.append((name, source, str(desc or ""), list(tags or [])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write recovered skills back")
    ap.add_argument("--glob", default="trace-*.jsonl")
    args = ap.parse_args()

    lib = SkillLibrary()
    have = set(lib.skills)
    found: dict[str, tuple] = {}
    game_of: dict[str, str] = {}

    for path in sorted(RESULTS.glob(args.glob)):
        # trace-<game>-<tag>.jsonl
        parts = path.stem.split("-")
        game = parts[1] if len(parts) > 2 else "?"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip() or "learn(" not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for name, source, desc, tags in learn_calls(row.get("code") or ""):
                found[name] = (name, source, desc, tags)
                game_of[name] = game

    missing = {n: v for n, v in found.items() if n not in have}
    print(f"traces scanned      : {len(list(RESULTS.glob(args.glob)))}")
    print(f"learn() skills found: {len(found)}")
    print(f"already in library  : {len(found) - len(missing)}")
    print(f"MISSING             : {len(missing)}")
    for n, (_, src, desc, tags) in missing.items():
        print(f"  - {n}  (from {game_of[n]}, tags={tags}, {len(src)} chars)")
        print(f"      {desc[:110]}")

    if not missing:
        print("\nnothing to recover")
        return 0
    if not args.apply:
        print("\nre-run with --apply to write these back")
        return 0

    restored = 0
    for name, (_, source, desc, tags) in missing.items():
        try:
            compile(source, f"<skill {name}>", "exec")
        except SyntaxError as exc:
            print(f"  SKIP {name}: does not compile ({exc})")
            continue
        lib.add(name, game_of[name], source, desc, tags)
        restored += 1
    print(f"\nrestored {restored} skill(s); library now holds {len(lib.skills)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
