"""Mutation-test the repeat-detection check.

A check that never fails is a lie that looks like evidence. Six of my own checks were
vacuous this session, every one of them because they looked for a NAME that survived
deleting the logic. So: break the mechanism three different ways and require the check
to notice each one, then prove the file came back byte-identical.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

SRC = Path("evals/arc/codeact_agent.py")
CHECK = ["python", "evals/arc/repeat_detection_check.py"]


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run() -> int:
    return subprocess.run(CHECK, capture_output=True, text=True).returncode


MUTATIONS = {
    "the recording is deleted (dict exists, nothing goes in)":
        lambda s: s.replace('        seen_outputs.setdefault(signature, []).append(turn + 1)\n', ''),
    "the agent is never told (warning block removed)":
        lambda s: re.sub(
            r'            if repeats >= 8:\n(?:.*\n)*?                \)\n',
            '            if repeats >= 8:\n                pass\n', s),
    "the message stops naming the earlier turns":
        lambda s: s.replace(
            'f"YOU HAVE ALREADY PRODUCED THIS RESULT {repeats} TIMES on this "\n'
            '                    f"level, most recently on turns {where}. The board may be changing "',
            '"YOU HAVE ALREADY PRODUCED THIS RESULT SEVERAL TIMES on this "\n'
            '                    "level. The board may be changing "'),
    "the tolerance is dropped (scolds the second look)":
        lambda s: s.replace('if repeats >= 8:', 'if repeats:'),
}


def main() -> int:
    original = SRC.read_text(encoding="utf-8")
    before = digest(SRC)

    if run() != 0:
        print("ABORT: the check is not green on unmutated source")
        return 1
    print(f"[baseline] check is GREEN, sha256 {before[:16]}")

    bad = 0
    for label, mutate in MUTATIONS.items():
        mutated = mutate(original)
        if mutated == original:
            print(f"[SKIP] {label}\n       mutation did not apply -- rewrite it")
            bad += 1
            continue
        SRC.write_text(mutated, encoding="utf-8")
        rc = run()
        SRC.write_text(original, encoding="utf-8")
        caught = rc != 0
        print(f"[{'CAUGHT' if caught else 'MISSED'}] {label}")
        bad += not caught

    after = digest(SRC)
    print("-" * 70)
    print(f"source restored byte-identical: {before == after}")
    if before != after:
        return 1
    print("mutation test: ALL CAUGHT" if not bad else f"mutation test: {bad} NOT CAUGHT")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
