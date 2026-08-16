"""Replay the fingerprint logic over real traces. Would it have fired, and when?

Building the detector is not evidence the detector detects anything. The whole
recurring defect class this session is machinery that runs while measuring nothing --
five instances, every one found by checking the ARTIFACT rather than reading the
source. So run the exact signature and threshold the harness now uses over the traces
already on disk, and report the turn each run would first have been warned on.

The number that matters is not "how many runs repeat" -- I already measured that. It
is how EARLY the warning arrives, because a warning at turn 110 of 120 buys nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

RESULTS = Path("eval/arc-results")


def signature(out: str) -> str:
    return hashlib.sha1(re.sub(r"\d+", "#", out or "").strip().encode("utf-8", "replace")).hexdigest()


def replay(path: Path) -> dict | None:
    seen: dict[str, list[int]] = {}
    first_warn = None
    turns = 0
    level = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if "output" not in row and "stdout" not in row:
            continue
        turns += 1
        lv = row.get("levels", level)
        if lv != level:  # level boundary clears the store, as the harness does
            seen.clear()
            level = lv
        sig = signature(row.get("output") or row.get("stdout") or "")
        seen.setdefault(sig, []).append(turns)
        if first_warn is None and len(seen[sig]) >= 3:
            first_warn = turns
    if not turns:
        return None
    worst = max((len(v) for v in seen.values()), default=0)
    return {"turns": turns, "first_warn": first_warn, "worst_repeat": worst}


def main() -> int:
    traces = sorted(RESULTS.glob("trace-*ev*.jsonl"), key=lambda p: p.stat().st_mtime)[-25:]
    if not traces:
        print("no ev traces found")
        return 1

    rows = []
    for t in traces:
        r = replay(t)
        if r:
            rows.append((t.name.replace("trace-", "").replace(".jsonl", ""), r))

    warned = [r for _, r in rows if r["first_warn"]]
    print(f"{'run':<16} {'turns':>6} {'1st warn':>9} {'saved':>7} {'worst':>6}")
    print("-" * 50)
    for name, r in sorted(rows, key=lambda kv: -(kv[1]["worst_repeat"])):
        fw = r["first_warn"]
        saved = (r["turns"] - fw) if fw else 0
        print(f"{name:<16} {r['turns']:>6} {str(fw or '-'):>9} {saved:>7} {r['worst_repeat']:>6}")

    print("-" * 50)
    print(f"runs replayed        : {len(rows)}")
    print(f"runs that would warn : {len(warned)}  ({len(warned)/len(rows):.0%})")
    if warned:
        fw = sorted(r["first_warn"] for r in warned)
        med = fw[len(fw) // 2]
        turns_after = sum(r["turns"] - r["first_warn"] for r in warned)
        print(f"median first warning : turn {med}")
        print(f"turns spent AFTER the warning would have arrived: {turns_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
