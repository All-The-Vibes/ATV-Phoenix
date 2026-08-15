"""How much does a mid-run reset actually cost, and how often does it happen?

Three checks went red at once and two of them describe the same event:

  level_monotonic_check : level counters read [1, 2, 3, 1, 2, 3] -- a run reaches
                          level 3 and finds itself back on level 1
  reset_check           : "trace-cd82-ev3: level count fell 3 -> 0. A reset really
                          does restart the game, and the prompt fix is wrong."

If that is rare, it is a curiosity. If it is common, it is the largest single leak in
the corpus, because a run that re-clears level 1 is spending its action budget on
levels it has already beaten -- and RHAE charges every one of those actions against the
same capped reward.

So count it: how many runs lose progress, how deep they were when it happened, and how
many turns they spend afterwards re-treading ground.

Free. Reads traces already on disk.
"""
from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path("eval/arc-results")


def rows(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
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
