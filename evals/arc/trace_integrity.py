"""Is this trace one run, or two runs in one file?

Two checks went red today describing a game that resets and destroys cleared levels:

  level_monotonic_check : "announced [1, 2, 3, 1, 2, 3] ... the gate has regressed"
  reset_check           : "level count fell 3 -> 0. A reset really does restart the
                           game, and the prompt fix is wrong."

Neither thing happened. Those traces hold two runs, concatenated by a tag collision:
240 rows against a 120-turn cap, every turn number present exactly twice. The level
counter did not fall; it started over, because a second run started over.

I spent twenty minutes measuring a phenomenon that does not exist, and got as far as a
table of "runs that lost levels mid-run" before the row count gave it away. A corrupted
measurement is worse than a missing one: it arrives with directions.

So this module answers the question once, and the checks that read traces can ask it
before they blame the harness. A trace is concatenated when a turn number ever fails to
increase -- turns are emitted 1, 2, 3, ... within a run, so a step backwards means a new
run began writing into the same file.

Importable and free.
"""
from __future__ import annotations

import json
from pathlib import Path


def turn_numbers(path: Path) -> list[int]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row.get("turn"), int):
            out.append(row["turn"])
    return out


def restart_points(turns: list[int]) -> list[int]:
    """Indices where the turn counter stopped increasing."""
    return [i for i in range(1, len(turns)) if turns[i] <= turns[i - 1]]


def is_concatenated(path: Path) -> bool:
    return bool(restart_points(turn_numbers(path)))


def segments(path: Path) -> list[tuple[int, int]]:
    """(start, end) row indices of each run inside the file, newest last."""
    turns = turn_numbers(path)
    if not turns:
        return []
    bounds = [0] + restart_points(turns) + [len(turns)]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def last_run_rows(path: Path) -> tuple[int, int]:
    """The row range of the MOST RECENT run in the file.

    A check that wants to judge current behaviour should read this, not the whole file.
    Reading the whole file is how a tag collision turns into a bug report about level
    resets.
    """
    segs = segments(path)
    return segs[-1] if segs else (0, 0)


def main() -> int:
    results = Path("eval/arc-results")
    bad = []
    for t in sorted(results.glob("trace-*.jsonl")):
        segs = segments(t)
        if len(segs) > 1:
            bad.append((t.name[6:-6], segs))

    if not bad:
        print("no concatenated traces found")
        return 0

    print(f"{'run':<20} {'runs in file':>13}  segment sizes")
    print("-" * 60)
    for name, segs in sorted(bad, key=lambda kv: -len(kv[1])):
        sizes = ", ".join(str(b - a) for a, b in segs)
        print(f"{name:<20} {len(segs):>13}  {sizes}")
    print("-" * 60)
    print(f"{len(bad)} trace file(s) contain more than one run.")
    print()
    print("These are tag collisions, not game resets. Any check or measurement that")
    print("reads them end-to-end will report level counters going backwards and")
    print("conclude the harness regressed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
