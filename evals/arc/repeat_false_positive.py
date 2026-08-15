"""Does the repeat warning fire on runs that WON?

92% of the stuck runs would warn, median turn 27. That number is worthless on its own,
because those 25 runs were selected for being stuck. A detector that also fires on
ft09's capped 6/6 is not a detector, it is a light that is always on -- and the harness
already has a graveyard of those.

So: replay the identical logic over the best-scoring run of every game that has cleared
its whole set, and over ft09 specifically, which scores 115.00% at 95 actions against a
208-action human baseline and cannot be improved. If the warning fires there, the
threshold is wrong.

The tail warning set the bar for this: 69 of 69 slow runs tripped, zero fast runs
wrongly tripped. Anything less than a clean separation is a message the agent should
learn to ignore.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

RESULTS = Path("eval/arc-results")

# Games whose best run cleared every level. These are the runs whose behaviour the
# harness must NOT interrupt.
WINNERS = ["ft09", "lp85", "tr87", "sb26", "vc33"]


def signature(out: str) -> str:
    return hashlib.sha1(re.sub(r"\d+", "#", out or "").strip().encode("utf-8", "replace")).hexdigest()


def replay(path: Path) -> dict | None:
    seen: dict[str, list[int]] = {}
    first_warn, turns, level, cleared = None, 0, 0, 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if "output" not in row and "stdout" not in row:
            continue
        turns += 1
        lv = row.get("levels", level)
        if lv != level:      # level boundary clears the store, as the harness does
            seen.clear()
            level = lv
            cleared = max(cleared, lv)
        sig = signature(row.get("output") or row.get("stdout") or "")
        seen.setdefault(sig, []).append(turns)
        if first_warn is None and len(seen[sig]) >= 3:
            first_warn = turns
    if not turns:
        return None
    return {"turns": turns, "first_warn": first_warn, "levels": cleared,
            "worst": max((len(v) for v in seen.values()), default=0)}


def main() -> int:
    print(f"{'run':<20} {'turns':>6} {'levels':>7} {'1st warn':>9} {'worst':>6}")
    print("-" * 54)
    fired = total = 0
    for game in WINNERS:
        for t in sorted(RESULTS.glob(f"trace-{game}-*.jsonl")):
            r = replay(t)
            if not r or r["levels"] < 5:      # only runs that got deep
                continue
            total += 1
            fired += bool(r["first_warn"])
            print(f"{t.name[6:-6]:<20} {r['turns']:>6} {r['levels']:>7} "
                  f"{str(r['first_warn'] or '-'):>9} {r['worst']:>6}")
    print("-" * 54)
    if not total:
        print("no deep runs found -- cannot judge false positives")
        return 1
    print(f"deep winning runs replayed : {total}")
    print(f"of those, warning fires on : {fired}  ({fired/total:.0%})")
    print()
    print("A clean detector fires near 0% here and near 100% on the stuck set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
