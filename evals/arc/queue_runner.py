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
# Run as a script, sys.path[0] is this directory rather than the repo root, so
# `evals.arc` is not importable without this.
sys.path.insert(0, str(ROOT))

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

    # ONE TOKEN FOR THE WHOLE QUEUE, AND IT HAS TO KEEP BEING VALID. Every agent
    # otherwise shells out to the Azure CLI for its own, and the CLI does not survive a
    # dozen callers at once: measured, ten of twelve runs sat at turn 1 on
    # ClientAuthenticationError while the endpoint was idle.
    #
    # Handing down the token STRING solved that and created a worse failure. A string
    # cannot be refreshed, so when it expires every agent fails forever with no recovery
    # path -- wave r2 lost twelve agents that way, each burning a 40-step retry ladder
    # against a credential that could never work again. The reasoning in the old comment
    # ("a token lasts about an hour and a run takes twenty minutes") was wrong twice: a
    # QUEUE runs for hours, not one run's worth of minutes, and `get_token` returns the
    # CLI's CACHED token, which can have any amount of life left. r2 died sixteen minutes
    # in, not sixty.
    #
    # So: still one fetcher, but via a file the children re-read. The parent refreshes it
    # below on every poll. No herd, and no expiry cliff.
    child_env = dict(os.environ)
    child_env.pop("ARC_AAD_TOKEN", None)  # the static form is the bug; never inherit it
    token_path = RESULTS / f"aad-token-{args.tag}.txt"
    child_env["ARC_AAD_TOKEN_FILE"] = str(token_path)

    def refresh_token(force: bool = False) -> None:
        """Rewrite the token file when it is missing or close to expiry.

        Refreshes on the parent's poll cadence, which is the whole point: a child that
        reads this file mid-run gets a live credential without ever calling the CLI.
        Failure is non-fatal -- the children fall back to their own credential, which is
        impolite but still plays.
        """
        try:
            if not force and token_path.exists():
                payload = json.loads(token_path.read_text(encoding="utf-8"))
                # Five minutes of headroom: long enough to cover a slow turn already in
                # flight when the refresh lands.
                if payload.get("expires_on", 0) - time.time() > 300:
                    return
        except (json.JSONDecodeError, OSError, ValueError):
            pass  # unreadable is the same as absent: refetch
        try:
            from evals.arc import aad

            tok = aad.credential().get_token(aad.SCOPE)
            tmp = token_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"token": tok.token, "expires_on": tok.expires_on}),
                encoding="utf-8",
            )
            # Atomic, so a child never reads a half-written credential.
            os.replace(tmp, token_path)
            left = (tok.expires_on - time.time()) / 60.0
            print(f"  token refreshed, {left:.0f} min of life", flush=True)
        except Exception as exc:
            print(f"  could not refresh the token ({type(exc).__name__}); "
                  f"agents will each fetch their own", flush=True)

    refresh_token(force=True)
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
        # BEFORE anything else in the pass, so a game admitted below starts against a live
        # credential and a game already running picks the new one up on its next turn.
        refresh_token()

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
    # The credential outlives the queue otherwise, sitting on disk with real life left.
    token_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
