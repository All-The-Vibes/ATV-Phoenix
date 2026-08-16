"""Is anything actually watching the corpus loop right now?

THE FAILURE THIS EXISTS FOR IS SILENCE. The loop has died twice without
announcing it: once napping at turn 1 on an auth timeout it reported as
congestion, once simply exiting after wave 26 while eight hours of compute went
unused. On both occasions every instrument that was consulted said healthy,
because every instrument answered a question about the loop and none answered
"is anyone still looking".

So this checks the WATCHER, not the loop. Three distinct ways to be blind, all
of them reported separately:

  * no health.json          -- nothing has ever watched
  * stale health.json       -- the watchdog died, and its last words are
                               still sitting there looking like news
  * health.json says down   -- the watchdog is alive and telling you the loop
                               is not

Staleness is the one worth the trouble. A file that exists and parses and is
four hours old is the exact shape of the outage it is meant to catch, and a
check that only tested existence would pass straight through it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HEALTH = (Path(__file__).resolve().parents[2] / "eval" / "arc-results"
          / "health.json")
# Two polls of slack: one missed cycle is a busy machine, two is a corpse.
STALE_MULTIPLE = 2


def main() -> int:
    if not HEALTH.exists():
        print(f"FAIL  no {HEALTH}")
        print("      nothing is watching the loop. Start the watchdog:")
        print("      python evals/arc/watchdog.py")
        return 1

    try:
        health = json.loads(HEALTH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"FAIL  {HEALTH.name} unreadable: {type(exc).__name__}: {exc}")
        return 1

    stamp = health.get("checked_at")
    if not stamp:
        print("FAIL  health.json has no checked_at; staleness cannot be judged")
        return 1
    try:
        seen = datetime.fromisoformat(stamp)
    except ValueError:
        print(f"FAIL  unparseable checked_at: {stamp!r}")
        return 1

    age = (datetime.now(timezone.utc) - seen).total_seconds()
    poll = int(health.get("poll_seconds", 300))
    budget = poll * STALE_MULTIPLE

    print(f"checked_at   : {stamp}  ({age:.0f}s ago)")
    print(f"poll         : {poll}s, stale past {budget}s")
    print(f"loop_running : {health.get('loop_running')}")
    print(f"agents       : {health.get('agents')}")
    print(f"auth errors  : {health.get('auth_errors_recent')}")
    print(f"restarts     : {health.get('restarts_this_watchdog')}")
    if health.get("summary"):
        print(f"last wave    : {health['summary']}")

    if age > budget:
        print(f"\nFAIL  health.json is {age:.0f}s old against a {budget}s budget.")
        print("      The watchdog is not running. Nothing is watching, and the")
        print("      file is stale enough to look like fresh news to a reader")
        print("      that only checked whether it existed.")
        return 1

    if not health.get("loop_running"):
        print("\nFAIL  the watchdog is alive and reports the loop is DOWN.")
        print("      That is the watchdog working -- check watchdog.log for the")
        print("      restart it attempted.")
        return 1

    print("\nOK    watchdog fresh, loop running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
