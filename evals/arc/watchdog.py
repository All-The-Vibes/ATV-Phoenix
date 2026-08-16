"""Keep the corpus loop alive, and make its death legible.

TWICE IN ONE DAY THE LOOP DIED WITHOUT ANYONE NOTICING. First on an Azure CLI
timeout that every agent reported as congestion, so three runs napped at turn 1
for 2h20m while `corpus_watch` cheerfully listed them as "in flight". Then again
overnight, when the process simply exited after wave 26 and eight hours of
compute went unused. Both times the instruments said healthy.

So this does two separate jobs, and the second matters more than the first:

  1. RESTART the loop when it is not running.
  2. WRITE DOWN what it saw, every cycle, with a timestamp.

The timestamp is the point. A watchdog that only restarts things fails the same
way the loop did -- silently, whenever the watchdog itself dies. Anything
reading `health.json` can compare `checked_at` against now and conclude the
watchdog is gone. Absence of the file, staleness of the file, and a failure
recorded IN the file are three different signals and all three are visible.

Deliberately dumb: no scoring, no API calls, no judgement about strategy. It
answers "is the thing running, and when did I last look".
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "eval" / "arc-results"
HEALTH = RESULTS / "health.json"
RUN_LOG = RESULTS / "auto-corpus-run.log"
WATCH_LOG = RESULTS / "watchdog.log"

POLL_SECONDS = 300
# Long enough that a slow turn is not mistaken for a hang. Agents write a line
# per turn and a turn can legitimately take minutes on a big board.
AGENT_SILENT_SECONDS = 1800

LOOP_ARGS = [
    "evals/arc/auto_corpus.py", "--waves", "0", "--concurrency", "3",
    "--max-turns", "120", "--patience", "90", "--tag-prefix", "ev",
]

# Windows: detach so the loop outlives this process and its console.
DETACHED = 0x00000008 | 0x00000200 | 0x08000000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def note(message: str) -> None:
    line = f"{now()} {message}"
    print(line, flush=True)
    try:
        with WATCH_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def processes() -> tuple[list[int], list[int]]:
    """(loop pids, agent pids) as the OS sees them right now."""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60,
        ).stdout
        data = json.loads(out) if out.strip() else []
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return [], []
    if isinstance(data, dict):
        data = [data]

    loops, agents = [], []
    for row in data:
        cmd = (row or {}).get("CommandLine") or ""
        pid = (row or {}).get("ProcessId")
        if not pid:
            continue
        # The watchdog itself runs python and must never count as the loop.
        if "watchdog.py" in cmd:
            continue
        if "auto_corpus.py" in cmd:
            loops.append(int(pid))
        elif "codeact_agent" in cmd:
            agents.append(int(pid))
    return loops, agents


def agent_activity() -> tuple[int, list[str]]:
    """Freshest agent log age in seconds, and any that look silent."""
    logs = sorted(RESULTS.glob("log-*-ev*.txt"),
                  key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    if not logs:
        return -1, []
    stale = []
    freshest = 10 ** 9
    for path in logs:
        age = int(time.time() - path.stat().st_mtime)
        freshest = min(freshest, age)
        if age > AGENT_SILENT_SECONDS:
            stale.append(f"{path.name}({age}s)")
    return freshest, stale


def auth_failures() -> int:
    """Auth errors in the newest agent logs -- the ev21 signature."""
    total = 0
    for path in sorted(RESULTS.glob("log-*-ev*.txt"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += body.count("ClientAuthenticationError")
    return total


def last_wave() -> dict:
    """Whatever the run log last said about a wave."""
    out = {"wave": None, "corpus": None, "delta": None}
    try:
        lines = RUN_LOG.read_text(encoding="utf-8",
                                  errors="replace").splitlines()
    except OSError:
        return out
    for line in reversed(lines):
        if "done in" in line and "corpus" in line:
            out["summary"] = line.strip()
            try:
                out["wave"] = int(line.split("wave")[1].split()[0])
            except (IndexError, ValueError):
                pass
            break
    for line in reversed(lines):
        if line.startswith("=== wave ") and "corpus" in line:
            try:
                out["corpus"] = line.split("corpus")[1].strip().rstrip("=").strip()
            except IndexError:
                pass
            break
    return out


def start_loop() -> int | None:
    try:
        proc = subprocess.Popen(
            [sys.executable, *LOOP_ARGS],
            cwd=str(ROOT),
            stdout=RUN_LOG.open("a", encoding="utf-8", buffering=1),
            stderr=subprocess.STDOUT,
            creationflags=DETACHED,
        )
        return proc.pid
    except OSError as exc:
        note(f"RESTART FAILED {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    note("watchdog up")
    restarts = 0
    while True:
        loops, agents = processes()
        freshest, stale = agent_activity()
        restarted = None

        if not loops:
            note("loop NOT RUNNING -- restarting")
            restarted = start_loop()
            restarts += 1
            if restarted:
                note(f"restarted loop pid={restarted}")
            time.sleep(30)
            loops, agents = processes()

        auth = auth_failures()
        if auth:
            note(f"WARNING {auth} auth error(s) in newest agent logs")

        health = {
            "checked_at": now(),
            "loop_running": bool(loops),
            "loop_pids": loops,
            "agents": len(agents),
            "agent_log_age_s": freshest,
            "stale_agent_logs": stale,
            "auth_errors_recent": auth,
            "restarts_this_watchdog": restarts,
            "last_restart_pid": restarted,
            "poll_seconds": POLL_SECONDS,
            **last_wave(),
        }
        tmp = HEALTH.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(health, indent=2), encoding="utf-8")
            tmp.replace(HEALTH)
        except OSError as exc:
            note(f"could not write health.json: {exc}")

        if stale:
            note(f"agents quiet: {', '.join(stale)}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
