"""Read the live state of in-flight runs off their traces. Costs no API calls.

Written after a monitor that grepped the LOG files reported deaths=0 for a run
that had already died nine times: the death notice is written to the trace, not
to the log, so the monitor was reporting the absence of a string from a file
that never contained it. The trace rows carry the run state as fields --
`turn`, `levels`, `total_actions` -- so read those instead of pattern-matching
prose.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[2] / "eval" / "arc-results"

# Human baselines, for pace. A run at 4/8 in 86 actions against a 388-action
# baseline is winning; the same 4/8 at 600 is not, and the level count alone
# cannot tell the two apart.
BASELINES = {
    "sb26": 213, "cd82": 171, "ft09": 208, "lp85": 388, "sc25": 350,
    "su15": 361, "vc33": 447, "r11l": 233, "tr87": 414, "tn36": 317,
    "sp80": 518, "bp35": 651, "ka59": 730, "ar25": 748, "ls20": 776,
    "cn04": 789, "g50t": 879, "sk48": 1070, "m0r0": 1107, "dc22": 1228,
    "re86": 1255, "lf52": 1339, "wa30": 1843, "tu93": None, "s5i5": None,
}


def read(run: str) -> dict | None:
    p = RESULTS / f"trace-{run}.jsonl"
    if not p.exists():
        return None
    rows = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A row still being written is truncated, not corrupt. Skipping
                # it is right; refusing the whole file over it is not.
                continue
    if not rows:
        return None

    deaths = sum(json.dumps(r).count("YOU DIED") for r in rows)
    last = rows[-1]
    return {
        "turn": last.get("turn", len(rows)),
        "levels": last.get("levels", 0),
        "actions": last.get("total_actions", 0),
        # Prefer the counter the run keeps over counting death notices in the
        # output, which only sees the deaths whose message survived truncation.
        "deaths": last.get("deaths", deaths),
        "mechanics": len(last.get("mechanics") or []),
        "notes": len(last.get("notes") or []),
        "bar": last.get("bar_colour"),
    }


def main(runs: list[str]) -> int:
    for spec in runs:
        game = spec.split("-")[0]
        s = read(spec)
        if s is None:
            print(f"{spec:<9} no trace yet")
            continue
        par = BASELINES.get(game)
        # Pace is only meaningful once a level is cleared: before that there is
        # no per-level spend to compare against anything.
        if par and s["levels"]:
            per = s["actions"] / s["levels"]
            pace = f"  {per:.0f} act/lvl vs par ~{par // max(1, s['levels'])}"
        else:
            pace = ""
        # Whether the bar was ever identified. On the eight games recorded as
        # bar-less this is the measurement that settles it, and it now comes free
        # with any run rather than costing one to ask.
        bar = "bar" if s.get("bar") is not None else "no-bar"
        print(
            f"{spec:<9} t{s['turn']:<4} lv={s['levels']:<3} "
            f"acts={s['actions']:<5} deaths={s['deaths']:<3} "
            f"mech={s['mechanics']:<3} {bar:<7}{pace}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
