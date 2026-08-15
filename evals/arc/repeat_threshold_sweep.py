"""Pick the repeat threshold from the separation, not from taste.

At >=3 repeats the warning fires on 92% of stuck runs and 39% of deep winning runs.
The second number is too high: a message that interrupts two of every five good runs
is one the agent learns to skim, and this harness already paid for that lesson.

So sweep the threshold and read the separation off the data, the way the tail warning
was calibrated (K=3 x human budget: 69 of 69 slow runs tripped, zero fast runs). Pick
the smallest threshold whose false-positive rate on deep winners is near zero while it
still catches the stuck set early enough to matter.

Both populations are read from the same traces with the same code, so the comparison
is like-for-like.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

RESULTS = Path("eval/arc-results")
WINNERS = ["ft09", "lp85", "tr87", "sb26", "vc33"]


def signature(out: str) -> str:
    return hashlib.sha1(re.sub(r"\d+", "#", out or "").strip().encode("utf-8", "replace")).hexdigest()


def rows(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "output" in r:
            yield r


def replay(path: Path, threshold: int) -> dict | None:
    seen: dict[str, list[int]] = {}
    first_warn, turns, level, deepest = None, 0, 0, 0
    for r in rows(path):
        turns += 1
        lv = r.get("levels", level)
        if lv != level:
            seen.clear()
            level = lv
            deepest = max(deepest, lv)
        sig = signature(r.get("output") or "")
        seen.setdefault(sig, []).append(turns)
        if first_warn is None and len(seen[sig]) >= threshold:
            first_warn = turns
    if not turns:
        return None
    return {"turns": turns, "first_warn": first_warn, "levels": deepest}


def main() -> int:
    stuck = sorted(RESULTS.glob("trace-*ev*.jsonl"), key=lambda p: p.stat().st_mtime)[-25:]
    winners = [t for g in WINNERS for t in sorted(RESULTS.glob(f"trace-{g}-*.jsonl"))]

    print(f"{'thresh':>6} {'stuck fires':>12} {'winner fires':>13} {'median warn':>12} {'separation':>11}")
    print("-" * 60)
    best = None
    for th in range(3, 9):
        s = [replay(t, th) for t in stuck]
        s = [r for r in s if r]
        w = [replay(t, th) for t in winners]
        w = [r for r in w if r and r["levels"] >= 5]
        sf = sum(bool(r["first_warn"]) for r in s) / max(1, len(s))
        wf = sum(bool(r["first_warn"]) for r in w) / max(1, len(w))
        fw = sorted(r["first_warn"] for r in s if r["first_warn"])
        med = fw[len(fw) // 2] if fw else 0
        sep = sf - wf
        print(f"{th:>6} {sf:>11.0%} {wf:>12.0%} {'turn ' + str(med):>12} {sep:>10.0%}")
        if best is None or sep > best[1]:
            best = (th, sep, wf, med)

    print("-" * 60)
    th, sep, wf, med = best
    print(f"best separation at threshold {th}: {sep:.0%} "
          f"(false positives {wf:.0%}, median warning turn {med})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
