"""Keep N game runs alive until the queue is empty.

The corpus is not short of ideas, it is short of wall clock. A game takes two to
four hours, the endpoint's tokens-per-minute is a fixed ceiling that three
concurrent runs already saturate, and the expensive failure mode is not a bad run
-- it is a finished run whose slot sits empty until someone notices.

So this owns the queue instead of a person owning it. It admits a game whenever
fewer than `--concurrency` agents are alive anywhere on the machine, not merely
among its own children, so it cooperates with runs that were launched by hand
rather than doubling the load on top of them.

Every game gets `--out` and `--trace`. A run that dies without either leaves no
record it was ever played, which is exactly how eight games came to show 0.00%
from a policy sweep that never called the model.

    python evals/arc/queue_runner.py --games ls20,g50t,sk48 --concurrency 3

Status is a single JSON file, so progress can be read without parsing logs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "eval" / "arc-results"

_CIM = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
    "| Where-Object { $_.CommandLine -like '*codeact_agent*' } "
    "| Measure-Object | Select-Object -ExpandProperty Count"
)


def agents_running() -> int:
    """How many game agents are alive on this machine, whoever started them."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _CIM],
            capture_output=True, text=True, timeout=60,
        )
        return int((out.stdout or "0").strip() or 0)
    except Exception:
        # Unknowable is not the same as zero. Claiming zero would admit every
        # queued game at once and bury the endpoint.
        return 10 ** 6


def write_status(state: dict, path: Path) -> None:
    try:
        tmp = path.with_suffix(".partial")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True, help="comma-separated game ids, in order")
    ap.add_argument("--tag", default="q", help="run-name suffix, e.g. ls20-q")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=160)
    ap.add_argument("--patience", type=int, default=90)
    ap.add_argument("--poll", type=int, default=60, help="seconds between admission checks")
    args = ap.parse_args()

    queue = [g.strip() for g in args.games.split(",") if g.strip()]
    RESULTS.mkdir(parents=True, exist_ok=True)

    # ONE TOKEN FOR THE WHOLE QUEUE. Every agent otherwise shells out to the Azure CLI
    # for its own, and the CLI does not survive a dozen callers at once: measured, ten
    # of twelve runs sat at turn 1 on ClientAuthenticationError while the endpoint was
    # idle. Fetched here, passed down, and never refreshed -- an AAD token lasts about
    # an hour and a run at this turn cap takes twenty minutes.
    child_env = dict(os.environ)
    if not child_env.get("ARC_AAD_TOKEN"):
        try:
            from azure.identity import DefaultAzureCredential

            tok = DefaultAzureCredential().get_token(
                "https://cognitiveservices.azure.com/.default"
            )
            child_env["ARC_AAD_TOKEN"] = tok.token
            print("  fetched one AAD token for the whole queue", flush=True)
        except Exception as exc:
            # Not fatal: each agent can still fetch its own, just less politely.
            print(f"  could not pre-fetch a token ({type(exc).__name__}); "
                  f"agents will each fetch their own", flush=True)
    # Per-tag, so two runners can drain two queues without overwriting each other's
    # status. Admission was already safe -- it counts live agents rather than reading
    # this file -- but a status file that flips between two writers is a file nobody
    # can trust, and an untrustworthy instrument is worse than none.
    status_path = RESULTS / f"queue-status-{args.tag}.json"

    started: list[dict] = []
    running: list[tuple[str, subprocess.Popen]] = []
    pending = list(queue)

    def snapshot(note: str) -> None:
        write_status({
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": note,
            "concurrency": args.concurrency,
            "queued": list(pending),
            "running": [g for g, _ in running],
            "started": started,
        }, status_path)

    snapshot("waiting for a free slot")
    print(f"queue: {' '.join(pending)} (concurrency {args.concurrency})", flush=True)

    while pending or running:
        for entry in list(running):
            game, proc = entry
            if proc.poll() is not None:
                running.remove(entry)
                print(f"  {game}: exited rc={proc.returncode}", flush=True)
                snapshot(f"{game} finished")

        while pending and len(running) < args.concurrency:
            alive = agents_running()
            if alive >= args.concurrency:
                snapshot(f"{alive} agent(s) alive; holding {len(pending)} in the queue")
                break

            game = pending.pop(0)
            run = f"{game}-{args.tag}"
            out = RESULTS / f"{run}.json"
            trace = RESULTS / f"trace-{run}.jsonl"
            log = RESULTS / f"log-{run}.txt"
            cmd = [
                sys.executable, "-m", "evals.arc.codeact_agent",
                "--games", game,
                "--max-turns", str(args.max_turns),
                "--patience", str(args.patience),
                "--out", str(out.relative_to(ROOT)).replace("\\", "/"),
                "--trace", str(trace.relative_to(ROOT)).replace("\\", "/"),
            ]
            handle = log.open("w", encoding="utf-8", buffering=1)
            proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=handle,
                                    stderr=subprocess.STDOUT, env=child_env)
            running.append((game, proc))
            started.append({
                "game": game, "run": run, "pid": proc.pid,
                "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            print(f"  {game}: started pid={proc.pid} -> {run}.json", flush=True)
            snapshot(f"{game} started")
            # Stagger, so agents do not open their first turn in the same second and
            # spend it colliding. Short now that the token is handed down: the collision
            # this used to space out was the credential fetch, not the model call.
            time.sleep(5)

        if pending or running:
            time.sleep(args.poll)

    snapshot("queue drained")
    print("queue drained", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
