"""Where is the corpus actually losing score?

The sampling loop answers "which game should run next". It never answers "what is
wrong with the harness", and that second question is where the large gains came from
this session: every double-digit jump today started with reading traces by hand and
finding a place the harness was silent or misleading.

  wrong objective     cd82  13.67% -> 61.68%
  batch synthesis     bp35  first level ever, after eight waves at zero
  level economics     vc33  14.80% -> 38.07%
  skill wiring        ft09  77.71% -> 115.00%, the RHAE cap

Every one of those was a diagnosis, not a replay. So this mechanises the diagnosis:
read every trace on disk, aggregate the failure shapes that cost score, and rank them
by the score they are costing. It proposes nothing and changes nothing -- it says
where to look, with the numbers behind it.

Five failure shapes, each measurable from the artifacts:

  TAIL        runs that passed 3x the human level-1 budget with nothing cleared.
              Measured 69 of 69 such runs finished slow, so every one is a whole run
              spent for a score near zero.
  STALL       levels that swallowed a large share of a run's actions. The corpus-wide
              observation behind the ask-on-stall messages was that most actions are
              spent after the last cleared level.
  CAPPED      games where the best run already sits at the ceiling for the levels it
              cleared. Efficiency work there earns exactly nothing; only a new LEVEL
              pays. This is the bug that cost six autonomous runs.
  LATE        games whose late levels score far worse than their early ones. RHAE
              weights by level index, so this is where the score actually leaks.
  SILENT      runs that died repeatedly while recording no mechanics -- the agent
              learning nothing from its failures, which is what the death-synthesis
              ask exists to fix.

    python evals/arc/diagnose.py
    python evals/arc/diagnose.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.arc.rhae import load_baselines, score_run  # noqa: E402

RESULTS = ROOT / "eval" / "arc-results"


def best_per_game(baselines: dict) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for path in sorted(RESULTS.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for run in payload.get("runs") or []:
            if not isinstance(run, dict) or "levels_completed" not in run:
                continue
            game = str(run.get("game") or "").split("-")[0]
            if game not in baselines:
                continue
            if run.get("start_level", 1) != 1 or run.get("scorable") is False:
                continue
            try:
                run["_score"] = score_run([run], baselines)["rhae_total"]
            except (KeyError, TypeError, ZeroDivisionError):
                continue
            if game not in best or run["_score"] > best[game]["_score"]:
                best[game] = run
    return best


def traces(recent_only: int = 0) -> list[tuple[str, str, list[dict]]]:
    """Every trace on disk, newest first.

    `recent_only` keeps just the N most recently written, which is the difference
    between "what has ever gone wrong" and "what is going wrong NOW". Over all
    history the top finding is bp35 failing eleven times -- true, and eight of those
    runs predate the fixes that gave it its first level. A diagnosis that cannot tell
    a solved problem from a live one will keep sending work at the solved one.
    """
    paths = sorted(RESULTS.glob("trace-*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if recent_only:
        paths = paths[:recent_only]
    out = []
    for path in paths:
        stem = path.stem[len("trace-"):]
        game = stem.split("-")[0]
        try:
            rows = [json.loads(l) for l in
                    path.read_text(encoding="utf-8").splitlines() if l.strip()]
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if rows:
            out.append((game, stem, rows))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--recent", type=int, default=40,
                    help="diagnose only the N newest traces; 0 for all history")
    args = ap.parse_args()

    baselines = load_baselines()
    best = best_per_game(baselines)
    share = 1.0 / max(1, len(baselines))
    findings: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "games": defaultdict(int), "cost_pp": 0.0, "detail": []})

    # CAPPED and LATE come from the scorecards: what the best run leaves on the table.
    for game, run in best.items():
        hb = baselines[game]
        lv = run["levels_completed"]
        weight_sum = sum(range(1, len(hb) + 1)) or 1
        ceiling = sum(range(1, lv + 1)) / weight_sum * 1.15
        room = ceiling - run["_score"]
        if lv and room < 0.005 and lv < len(hb):
            f = findings["CAPPED"]
            f["count"] += 1
            f["games"][game] += 1
            # Efficiency cannot pay here; only the next level can.
            f["cost_pp"] += ((lv + 1) / weight_sum * 1.15) * share * 100
            f["detail"].append(f"{game}: {lv}/{len(hb)} levels, at its {ceiling:.1%} "
                               f"ceiling -- only a NEW LEVEL can pay")

        la = run.get("level_actions") or []
        if len(la) >= 3:
            scores = [min(1.15, (hb[i] / max(1, la[i])) ** 2)
                      for i in range(min(len(la), len(hb)))]
            half = len(scores) // 2
            early = sum(scores[:half]) / max(1, half)
            late = sum(scores[half:]) / max(1, len(scores) - half)
            if early > 0.25 and late < early / 3:
                f = findings["LATE"]
                f["count"] += 1
                f["games"][game] += 1
                f["cost_pp"] += room * share * 100
                f["detail"].append(
                    f"{game}: early levels avg {early:.0%}, late {late:.0%} "
                    f"({room * share * 100:.2f}pp of corpus left on the table)")

    # TAIL, STALL and SILENT come from the traces: what a run did while it happened.
    for game, stem, rows in traces(args.recent):
        if game not in baselines:
            continue
        hb1 = baselines[game][0]
        last = rows[-1]
        cleared = last.get("levels") or 0
        total = last.get("total_actions") or 0

        if cleared == 0 and total >= 3 * hb1:
            f = findings["TAIL"]
            f["count"] += 1
            f["games"][game] += 1
            f["cost_pp"] += share * 100 * 0.5   # a whole run, scoring ~nothing
            f["detail"].append(f"{stem}: {total} actions, {total / hb1:.1f}x human, "
                               f"never cleared level 1")

        if cleared and total:
            first = next((r for r in rows if (r.get("levels") or 0) > 0), None)
            after = total - (first["total_actions"] if first else 0)
            if after > 0.6 * total and total > 200:
                f = findings["STALL"]
                f["count"] += 1
                f["games"][game] += 1
                # Those actions bought nothing and RHAE squares them, so the cost is
                # the gap between what these levels scored and what they could have.
                # `level_actions` lives on the SCORECARD, not in the trace -- reading
                # it from the trace row silently produced a cost of zero on every
                # finding, which is how a diagnosis reports a real problem as free.
                hb_used = baselines[game][:cleared]
                run_for_game = best.get(game) or {}
                la_now = (run_for_game.get("level_actions") or [])[:cleared]
                if hb_used and la_now and len(la_now) == len(hb_used):
                    ws = sum(range(1, len(baselines[game]) + 1)) or 1
                    got = sum((i + 1) * min(1.15, (hb_used[i] / max(1, la_now[i])) ** 2)
                              for i in range(len(la_now))) / ws
                    ideal = sum((i + 1) * 1.15 for i in range(len(la_now))) / ws
                    f["cost_pp"] += max(0.0, ideal - got) * share * 100 * 0.1
                f["detail"].append(f"{stem}: {after}/{total} actions "
                                   f"({after / total:.0%}) spent after the last clear")

        deaths = last.get("deaths") or 0
        mechs = len(last.get("mechanics") or [])
        if deaths >= 8 and mechs <= 1:
            f = findings["SILENT"]
            f["count"] += 1
            f["games"][game] += 1
            # A run that dies repeatedly and records nothing has spent the run without
            # buying the one thing a death is good for. Charged as a fraction of a run.
            f["cost_pp"] += share * 100 * 0.25
            f["detail"].append(f"{stem}: {deaths} deaths, {mechs} mechanics learned")

    ranked = sorted(findings.items(), key=lambda kv: -kv[1]["cost_pp"])
    if args.json:
        print(json.dumps({k: {"count": v["count"], "cost_pp": round(v["cost_pp"], 2),
                              "games": dict(v["games"])} for k, v in ranked}, indent=2))
        return 0

    print("WHERE THE CORPUS IS LOSING SCORE"
          f" ({'last ' + str(args.recent) + ' traces' if args.recent else 'all history'}"
          " + every scorecard)\n")
    for name, f in ranked:
        top = sorted(f["games"].items(), key=lambda kv: -kv[1])[:6]
        print(f"{name:8} {f['count']:>4} occurrence(s)   "
              f"~{f['cost_pp']:.2f}pp of corpus at stake")
        print(f"         worst: {', '.join(f'{g}({n})' for g, n in top)}")
        for line in f["detail"][:3]:
            print(f"           {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
