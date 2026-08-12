"""Live monitor for an in-flight corpus wave: state, pace, and what is going WRONG.

`monitor.py` reads ``mission-*.json``. `queue_runner.py` writes ``{game}-{tag}.json``.
Those have never matched, so throughout a twelve-agent wave with fourteen levels cleared
the monitor printed ``games finished : 0/25, levels cleared : 0``. A monitor that reports
zero while the run is working is worse than no monitor, because it gets believed. This
reads what the queue runner actually writes.

Three sources, merged, because no single one is sufficient:

* the queue status file -- the only place the QUEUED games exist. A card-only view cannot
  see work that has not started and silently under-reports the wave.
* the per-game result cards -- authoritative for a finished game, and checkpointed every
  turn while in flight, which is what makes live RHAE possible at all.
* the traces -- the freshest signal, and the only one with a MTIME. A hung agent keeps a
  perfectly valid card forever; the trace is how you tell "thinking" from "dead".

The alerts are the point. Every one is a failure this repo has actually shipped:

* ``STALLED`` -- the trace stopped moving. A dead agent used to be visible only as a wave
  that never finished.
* ``DEAD`` -- the PID is gone with the card still ``in_progress``. Ten of twelve agents
  once died at turn 1 on ClientAuthenticationError and the wave looked "running" for
  hours.
* ``PATIENCE`` -- fired already, and it is reported with the mechanics the run was holding
  when it died, because "stopped at 0 levels" and "stopped at 0 levels while holding a
  correct control model" are different bugs with different fixes.
* ``PATIENCE RISK`` -- close to the cut and still learning. This is the one that would
  have caught ``--patience 25`` on the night it was set, instead of after five games died.

Read-only. It never writes into ``eval/arc-results``: `standings.py` globs ``*.json``
there and scores any file carrying a ``runs`` key, so a snapshot dropped in that directory
would be counted as a run and inflate the corpus. Snapshots go to ``eval/arc-monitor``.

Usage::

    python -m evals.arc.wavewatch                # print once
    python -m evals.arc.wavewatch --watch 60     # refresh every 60s
    python -m evals.arc.wavewatch --json         # machine-readable
    python -m evals.arc.wavewatch --teams        # one paragraph for a chat message
    python -m evals.arc.wavewatch --tag r2       # pin a wave; default is the newest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RESULTS = ROOT / "eval" / "arc-results"
SNAPSHOTS = ROOT / "eval" / "arc-monitor"

CORPUS_GAMES = 25
CORPUS_LEVELS = 183
PRIME_AGENT = 0.955

# A trace quiet for this long is not thinking. One turn is a model call plus its actions;
# minutes are normal, a quarter of an hour is not.
STALL_MIN = 15.0
# How close to the patience cut counts as "about to be killed".
PATIENCE_WARN = 5

# Baselines cost an API round trip, so a --watch loop must not refetch them every pass.
_BASELINES: dict[str, list[int]] | None = None
_BASELINE_CACHE = SNAPSHOTS / "baselines.json"


def baselines() -> dict[str, list[int]]:
    """Per-level human action counts, fetched once and cached on disk.

    Falls back to the cache when the API is unreachable and to ``{}`` when there is no
    cache. Returning empty is deliberate: the monitor then omits RHAE rather than printing
    a made-up number, since a wrong score here would be quoted later as a measurement.
    """
    global _BASELINES
    if _BASELINES is not None:
        return _BASELINES
    try:
        from evals.arc.rhae import load_baselines

        _BASELINES = load_baselines()
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        _BASELINE_CACHE.write_text(json.dumps(_BASELINES), encoding="utf-8")
    except Exception:
        try:
            _BASELINES = json.loads(_BASELINE_CACHE.read_text(encoding="utf-8"))
        except Exception:
            _BASELINES = {}
    return _BASELINES


def newest_tag() -> str | None:
    files = sorted(
        RESULTS.glob("queue-status-*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not files:
        return None
    return files[0].stem[len("queue-status-") :]


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # A file mid-write is transient, not fatal: the next refresh gets it.
        return None


def alive(pid: int) -> bool:
    """Whether a PID is still running, without importing psutil."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import subprocess

        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=15,
            ).stdout
        except Exception:
            return True  # unknown is not proof of death
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def trace_state(tag: str, game: str) -> dict:
    """Freshness and last-row state for one run's trace."""
    path = RESULTS / f"trace-{game}-{tag}.jsonl"
    if not path.exists():
        return {"trace": False}
    quiet = (time.time() - path.stat().st_mtime) / 60.0
    last = None
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    continue  # truncated tail row, still being written
    except OSError:
        return {"trace": False}
    if last is None:
        return {"trace": False}
    return {
        "trace": True,
        "quiet_min": round(quiet, 1),
        "turn": last.get("turn", 0),
        "levels": last.get("levels", 0),
        "actions": last.get("total_actions", 0),
        "deaths": last.get("deaths", 0),
        "mechanics": len(last.get("mechanics") or []),
    }


def collect(tag: str) -> dict:
    status = read_json(RESULTS / f"queue-status-{tag}.json") or {}
    pids = {e.get("game"): e.get("pid", 0) for e in status.get("started", [])}

    games: list[dict] = []
    alerts: list[str] = []

    for path in sorted(RESULTS.glob(f"*-{tag}.json")):
        if path.name.startswith("queue-status-"):
            continue
        payload = read_json(path)
        if not payload:
            continue
        runs = payload.get("runs") or []
        if not runs:
            continue
        run = runs[0]
        game = str(run.get("game") or path.stem.rsplit("-", 1)[0])
        live = trace_state(tag, game)
        stopped = run.get("stopped", "?")
        in_flight = stopped == "in_progress"

        # The trace outruns the card: the card is rewritten once per turn, the trace row is
        # appended as the turn happens. Prefer whichever is further along so a game is never
        # reported as behind where it demonstrably is.
        turns = max(run.get("turns_used", 0), live.get("turn", 0) or 0)
        levels = max(run.get("levels_completed", 0), live.get("levels", 0) or 0)

        row = {
            "game": game,
            "levels": levels,
            "available": run.get("win_levels", 0),
            "actions": max(run.get("actions_spent", 0), live.get("actions", 0) or 0),
            "level_actions": run.get("level_actions") or [],
            "deaths": max(run.get("deaths", 0), live.get("deaths", 0) or 0),
            "turns": turns,
            "max_turns": run.get("max_turns", 0),
            "mechanics": len(run.get("mechanics_learned") or []),
            "tokens": run.get("tokens", 0),
            "elapsed_min": round(run.get("elapsed_s", 0) / 60.0, 1),
            "stopped": stopped,
            "in_flight": in_flight,
            "quiet_min": live.get("quiet_min"),
            "pid": pids.get(game, 0),
        }
        games.append(row)

        if in_flight:
            quiet = live.get("quiet_min")
            if quiet is not None and quiet >= STALL_MIN:
                alerts.append(
                    f"STALLED  {game}: trace quiet {quiet:.0f} min at turn {turns}"
                )
            pid = row["pid"]
            if pid and not alive(pid):
                alerts.append(
                    f"DEAD     {game}: pid {pid} gone, card still in_progress "
                    f"(turn {turns}, {levels} levels)"
                )
        elif stopped == "patience":
            held = row["mechanics"]
            alerts.append(
                f"PATIENCE {game}: cut at turn {turns}/{row['max_turns']} with "
                f"{levels} levels, holding {held} mechanic(s), {row['deaths']} deaths"
            )

        games[-1] = row

    # Patience risk needs the wave's configured patience, which lives on the child command
    # line rather than in any file. Infer it from the games it already killed: a cut always
    # happens exactly `patience` turns after the last level gain, and with zero levels that
    # is simply the turn count. Without a kill to learn from there is nothing to warn about,
    # which is correct -- guessing a threshold would produce false alarms.
    cut_turns = [
        g["turns"] for g in games if g["stopped"] == "patience" and g["levels"] == 0
    ]
    patience = min(cut_turns) if cut_turns else None
    if patience:
        for g in games:
            if not g["in_flight"] or g["levels"] > 0:
                continue
            left = patience - g["turns"]
            if 0 < left <= PATIENCE_WARN:
                alerts.append(
                    f"AT RISK  {g['game']}: {left} turn(s) from the patience cut at 0 "
                    f"levels, holding {g['mechanics']} mechanic(s)"
                )

    scored = {}
    base = baselines()
    if base and games:
        try:
            from evals.arc.rhae import score_run

            scored = score_run(
                [
                    {
                        "game": g["game"],
                        "levels_completed": g["levels"],
                        "actions_spent": g["actions"],
                        "level_actions": g["level_actions"],
                    }
                    for g in games
                ],
                base,
            )
        except Exception:
            scored = {}

    running = [g for g in games if g["in_flight"]]
    return {
        "tag": tag,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "queued": status.get("queued", []),
        "concurrency": status.get("concurrency", 0),
        "games": sorted(games, key=lambda g: (-g["levels"], g["game"])),
        "running": len(running),
        "finished": len(games) - len(running),
        "levels": sum(g["levels"] for g in games),
        "available": sum(g["available"] for g in games),
        "deaths": sum(g["deaths"] for g in games),
        "actions": sum(g["actions"] for g in games),
        "tokens": sum(g["tokens"] for g in games),
        "patience_inferred": patience,
        "rhae_percent": scored.get("rhae_percent"),
        "alerts": alerts,
    }


def render(s: dict) -> str:
    total = len(s["games"]) + len(s["queued"])
    head = [
        f"ARC wave '{s['tag']}'   {datetime.now():%H:%M:%S}",
        f"  games      : {s['finished']} done, {s['running']} running, "
        f"{len(s['queued'])} queued  ({total} in wave, {CORPUS_GAMES} in corpus)",
        f"  levels     : {s['levels']}/{s['available']} attempted"
        f"   |  {s['levels']}/{CORPUS_LEVELS} corpus",
    ]
    if s["rhae_percent"] is not None:
        gap = PRIME_AGENT * 100 - s["rhae_percent"]
        head.append(
            f"  RHAE       : {s['rhae_percent']:.2f}%   "
            f"(Prime Agent 95.50%, gap {gap:.2f}pp)"
        )
    else:
        head.append("  RHAE       : unavailable (no baselines; monitor stays silent)")
    head.append(
        f"  spend      : {s['actions']:,} actions, {s['deaths']} deaths, "
        f"{s['tokens'] / 1e6:.1f}M tokens"
    )

    rows = [
        "",
        f"  {'game':<6} {'lv':>6} {'acts':>6} {'die':>4} {'turns':>8} "
        f"{'mech':>5} {'min':>6}  state",
    ]
    for g in s["games"]:
        turns = f"{g['turns']}/{g['max_turns']}"
        state = g["stopped"]
        if g["in_flight"]:
            quiet = g["quiet_min"]
            state = f"live ({quiet:.0f}m quiet)" if quiet is not None else "live"
        rows.append(
            f"  {g['game']:<6} {str(g['levels']) + '/' + str(g['available']):>6} "
            f"{g['actions']:>6} {g['deaths']:>4} {turns:>8} {g['mechanics']:>5} "
            f"{g['elapsed_min']:>6.1f}  {state}"
        )
    if s["queued"]:
        rows.append(f"  queued: {', '.join(s['queued'])}")

    tail = [""]
    if s["alerts"]:
        tail.append(f"  ALERTS ({len(s['alerts'])}):")
        tail += [f"    {a}" for a in s["alerts"]]
    else:
        tail.append("  ALERTS: none")
    if s["patience_inferred"]:
        tail.append(
            f"  (patience inferred at {s['patience_inferred']} turns from observed cuts)"
        )
    return "\n".join(head + rows + tail)


def teams(s: dict) -> str:
    bits = [
        f"**ARC wave `{s['tag']}`** - {s['levels']}/{s['available']} levels across "
        f"{len(s['games'])} games ({s['finished']} done, {s['running']} running, "
        f"{len(s['queued'])} queued)."
    ]
    if s["rhae_percent"] is not None:
        bits.append(
            f"RHAE **{s['rhae_percent']:.2f}%** vs Prime Agent 95.50%."
        )
    bits.append(
        f"Spend: {s['actions']:,} actions, {s['deaths']} deaths, "
        f"{s['tokens'] / 1e6:.1f}M tokens."
    )
    if s["alerts"]:
        bits.append(f"\n\n**{len(s['alerts'])} alert(s):**")
        bits += [f"\n- {a}" for a in s["alerts"]]
    else:
        bits.append("No alerts.")
    return " ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="", help="wave tag; default is the newest")
    ap.add_argument("--watch", type=int, default=0, help="refresh every N seconds")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--teams", action="store_true", help="one paragraph for chat")
    ap.add_argument("--snapshot", action="store_true",
                    help="also write eval/arc-monitor/wave-<tag>.json")
    args = ap.parse_args()

    while True:
        tag = args.tag or newest_tag()
        if not tag:
            print("no queue-status-*.json in eval/arc-results; no wave to watch")
            return 1
        state = collect(tag)

        if args.json:
            print(json.dumps(state, indent=2), flush=True)
        elif args.teams:
            print(teams(state), flush=True)
        else:
            print(render(state), flush=True)

        if args.snapshot:
            SNAPSHOTS.mkdir(parents=True, exist_ok=True)
            (SNAPSHOTS / f"wave-{tag}.json").write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )

        if not args.watch:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
