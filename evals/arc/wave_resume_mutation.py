"""Mutation-test the wave-resume check.

The bug this guards was invisible for four restarts and cost six tags of evidence. A
check that cannot detect it reintroduced would let that happen a fifth time, so break
it four ways -- including the two subtle ones, where resume_wave exists but main()
ignores it, and where a corrupt line silently resets the counter.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

SRC = Path("evals/arc/auto_corpus.py")
CHECK = ["python", "evals/arc/wave_resume_check.py"]


def rc() -> int:
    return subprocess.run(CHECK, capture_output=True, text=True).returncode


MUTATIONS = {
    "the original bug: main() seeds wave = 0 again":
        lambda s: s.replace("    wave = resume_wave()", "    wave = 0", 1),
    "resume_wave exists but always reports a fresh workspace":
        lambda s: s.replace(
            '    if not ledger.exists():\n        return 0',
            '    if True:\n        return 0', 1),
    "a torn final line resets the counter instead of being skipped":
        lambda s: s.replace(
            "        except Exception:\n            continue",
            "        except Exception:\n            return 0", 1),
    "the resume is computed and then thrown away":
        lambda s: s.replace("    wave = resume_wave()",
                            "    wave = resume_wave() and 0", 1),
}


def main() -> int:
    original = SRC.read_text(encoding="utf-8")
    before = hashlib.sha256(SRC.read_bytes()).hexdigest()

    if rc() != 0:
        print("ABORT: check is not green on unmutated source")
        return 1
    print(f"[baseline] check GREEN, sha256 {before[:16]}")

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
