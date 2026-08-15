"""Mutation-test the guidance auditor.

The auditor just returned a clean bill of health. A clean result from a tool that
cannot detect anything is worse than no result, because it closes an investigation.
So reintroduce both bugs the class has actually produced -- the erasure from c07ff22
and the untraced message from 291aa66 -- and require the auditor to catch each.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

SRC = Path("evals/arc/codeact_agent.py")
AUDIT = ["python", "evals/arc/guidance_audit.py"]


def rc() -> int:
    return subprocess.run(AUDIT, capture_output=True, text=True).returncode


def _erase_a_later_append(s: str) -> str:
    """Reproduce c07ff22 faithfully: a plain assignment AFTER earlier appends.

    The first attempt converted the FIRST `consolidate +=` and the auditor passed it --
    correctly. Turning the first append into an assignment leaves "assign, then append,
    then append", which erases nothing. The bug that actually shipped was a later branch
    using `=` and wiping out everything composed before it. Mutate the LAST append.
    """
    marker = "        consolidate += ("
    idx = s.rfind(marker)
    if idx == -1:
        return s
    return s[:idx] + "        consolidate = (" + s[idx + len(marker):]


MUTATIONS = {
    "c07ff22 reintroduced: a later append becomes a plain assignment":
        _erase_a_later_append,
    "291aa66 reintroduced: the message stops reaching the trace":
        lambda s: s.replace('"consolidate": consolidate', '"unused_key": 1', 1),
}


def main() -> int:
    original = SRC.read_text(encoding="utf-8")
    before = hashlib.sha256(SRC.read_bytes()).hexdigest()

    if rc() != 0:
        print("ABORT: auditor is not green on unmutated source")
        return 1
    print(f"[baseline] auditor GREEN, sha256 {before[:16]}")

    bad = 0
    for label, mutate in MUTATIONS.items():
        mutated = mutate(original)
        if mutated == original:
            print(f"[SKIP] {label}\n       mutation did not apply -- rewrite it")
            bad += 1
            continue
        SRC.write_text(mutated, encoding="utf-8")
        caught = rc() != 0
        SRC.write_text(original, encoding="utf-8")
        print(f"[{'CAUGHT' if caught else 'MISSED'}] {label}")
        bad += not caught

    after = hashlib.sha256(SRC.read_bytes()).hexdigest()
    print("-" * 70)
    print(f"source restored byte-identical: {before == after}")
    if before != after:
        return 1
    print("mutation test: ALL CAUGHT" if not bad else f"mutation test: {bad} NOT CAUGHT")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
