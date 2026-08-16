"""How much does a mid-run reset actually cost, and how often does it happen?

WRITTEN TO CHASE A PHANTOM, KEPT AS THE PROOF IT WAS ONE.

Three checks went red at once and two described the same event -- level counters reading
[1, 2, 3, 1, 2, 3], and "level count fell 3 -> 0. A reset really does restart the game,
and the prompt fix is wrong." This tool was written to size the damage before fixing it,
and its first answer was: 7 of 318 runs lost levels mid-run, 22 levels thrown away, 750
turns spent re-treading ground.

Every one of those numbers was wrong. The flagged traces held 240 rows against a
120-turn cap: two runs concatenated into one file by a tag collision. The level counter
never fell, it started over, because a second run started over. Filtered to the most
recent run per file, the honest count is zero, and reset_check now reports 278 recorded
runs that never lost a cleared level across every death.

Kept because the retraction is worth more than the tool: a corrupted measurement is more
expensive than a missing one, since it arrives with directions attached. Run it to
confirm the phenomenon still does not exist.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arc.trace_integrity import last_run_rows  # noqa: E402

RESULTS = Path("eval/arc-results")


def rows(path: Path):
    """Only the most recent run in the file -- see the module docstring."""
    lo, hi = last_run_rows(path)
    index = -1
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if isinstance(r.get("turn"), int):
            index += 1
            if not (lo <= index < hi):
                continue
        if "levels" in r:
            yield r


def scan(path: Path) -> dict | None:
    seq, turns = [], 0
    for r in rows(path):
        turns += 1
        seq.append(r.get("levels") or 0)
    if not seq:
        return None
    drops, lost, turns_after = 0, 0, 0
    peak = 0
    for i, lv in enumerate(seq):
        if lv < peak:
            drops += 1
            lost += peak - lv
            if turns_after == 0:
                turns_after = len(seq) - i
            peak = lv
        peak = max(peak, lv)
    return {"turns": turns, "peak": max(seq), "final": seq[-1],
            "drops": drops, "lost": lost, "turns_after": turns_after}


def main() -> int:
    traces = sorted(RESULTS.glob("trace-*.jsonl"))
    hit, total, lost_total, wasted = [], 0, 0, 0
    for t in traces:
        s = scan(t)
        if not s:
            continue
        total += 1
        if s["drops"]:
            hit.append((t.name[6:-6], s))
            lost_total += s["lost"]
            wasted += s["turns_after"]

    hit.sort(key=lambda kv: -kv[1]["lost"])
    print(f"{'run':<20} {'turns':>6} {'peak':>5} {'final':>6} {'drops':>6} "
          f"{'levels lost':>12} {'turns after':>12}")
    print("-" * 74)
    for name, s in hit[:20]:
        print(f"{name:<20} {s['turns']:>6} {s['peak']:>5} {s['final']:>6} "
              f"{s['drops']:>6} {s['lost']:>12} {s['turns_after']:>12}")

    print("-" * 74)
    print(f"runs scanned                  : {total}")
    print(f"runs that LOST levels mid-run : {len(hit)}  ({len(hit)/max(1,total):.0%})")
    print(f"total levels thrown away      : {lost_total}")
    print(f"turns spent after the first loss: {wasted}")
    print()
    print("Every one of those turns is re-clearing a level the run had already beaten,")
    print("and RHAE charges the actions against a reward that is capped at 1.15.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
