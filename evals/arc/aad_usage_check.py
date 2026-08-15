"""Does the ARC code actually go through the fixed credential helper?

A FIX NOBODY CALLS IS NOT A FIX. `evals/arc/aad.py` sets the CLI process timeout
that keeps a wave alive, and `auth_check.py` proves that helper works. Neither
says a word about whether the agents USE it. Six modules built their own
`DefaultAzureCredential()` -- every one of them silently taking the 10s default
that stalled ev21 for 2h20m -- and both of those checks would have stayed green
through all six.

So this one greps for the constructor. Any construction outside the helper is
the bug, because the library default is the bug.
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
OWNER = "aad.py"
SELF = pathlib.Path(__file__).name
CALL = re.compile(r"\bDefaultAzureCredential\s*\(")


def main() -> int:
    offenders: list[tuple[str, int, str]] = []
    scanned = 0
    for path in sorted(HERE.glob("*.py")):
        if path.name in (OWNER, SELF):
            continue
        scanned += 1
        for n, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if CALL.search(line):
                offenders.append((path.name, n, line.strip()))

    print(f"scanned  : {scanned} modules in {HERE}")
    print(f"helper   : {OWNER}")

    if offenders:
        print(f"\nFAIL  {len(offenders)} direct construction(s); each one takes the")
        print("      library's 10s CLI timeout instead of the helper's:")
        for name, n, line in offenders:
            print(f"        {name}:{n}  {line}")
        print(f"\n      Use `from evals.arc import aad` and `aad.credential()`.")
        return 1

    print("\nOK    every credential comes from the helper")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
