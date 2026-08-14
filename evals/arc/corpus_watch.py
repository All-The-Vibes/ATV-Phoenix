"""Is the loop actually improving anything?

`auto_corpus.py` writes a row per wave. This reads them back and answers the only
questions worth asking of an autonomous run: is the corpus moving, which waves paid,
which games are converting, and is anything alive right now.

Deliberately read-only and free. It never launches, never scores a game, never
touches the library -- a monitor that can change what it measures is not a monitor.

    python evals/arc/corpus_watch.py
    python evals/arc/corpus_watch.py --json     # for anything downstream
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RESULTS = ROOT / "eval" / "arc-results"
LEDGER = RESULTS / "auto-corpus-ledger.jsonl"
PRIME_AGENT = 0.955


def rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def live() -> list[str]:
    """Which games are being played right now, straight from the process table."""
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
           "Where-Object { $_.CommandLine -like '*codeact_agent*' } | "
           "ForEach-Object { ($_.CommandLine -split '--games ')[1].Split(' ')[0] }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, text=True, timeout=90)
        return [g for g in (out.stdout or "").split() if g]
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = rows()
    waves = [r for r in data if r.get("event") == "wave"]
    start = next((r for r in data if r.get("event") == "start"), None)

    running = live()

    # LIVE, not last-recorded. The ledger only gets a row when a wave FINISHES, so
    # mid-wave gains are invisible to it -- and that is not hypothetical: this tool
    # reported "0 waves produced a gain, corpus 24.93%" while an in-flight wave had
    # already taken r11l from 9.80% to 51.19% and the corpus to 26.59%. A monitor that
    # under-reports progress is as misleading as one that over-reports it.
    from evals.arc.auto_corpus import corpus_now  # noqa: PLC0415 - avoids a cycle
    from evals.arc.rhae import load_baselines     # noqa: PLC0415
    corpus, levels = corpus_now(load_baselines())
    started = (start or {}).get("corpus", corpus)

    payload = {
        "corpus": corpus,
        "levels": levels,
        "gap_to_prime_pp": round((PRIME_AGENT - corpus) * 100, 2),
        "waves_run": len(waves),
        "gained_pp_since_start": round((corpus - started) * 100, 3),
        "waves_that_paid": sum(1 for w in waves if w.get("delta", 0) > 0),
        "running_now": running,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"corpus            : {corpus:.2%}   ({levels} levels)")
    print(f"gap to Prime Agent: {payload['gap_to_prime_pp']:.2f}pp")
    print(f"waves run         : {len(waves)}  "
          f"({payload['waves_that_paid']} produced a gain)")
    print(f"since loop start  : {payload['gained_pp_since_start']:+.3f}pp")
    print(f"running now       : {', '.join(running) if running else 'nothing'}")

    if waves:
        print("\nlast waves:")
        for w in waves[-8:]:
            when = w.get("at", "")[11:19]
            games = ",".join(w.get("games", []))
            print(f"  {when}  {w.get('tag','?'):8} {games:22} "
                  f"{w.get('corpus_before',0):.2%} -> {w.get('corpus_after',0):.2%}  "
                  f"{w.get('delta',0):+.3%}  {w.get('elapsed_s',0)}s")

        # Which games have actually converted, so the ranker can be judged rather
        # than trusted. A game picked repeatedly that never pays is a signal the EV
        # model is wrong about it.
        seen: dict[str, list[float]] = {}
        for w in waves:
            for g in w.get("games", []):
                seen.setdefault(g, []).append(w.get("delta", 0.0))
        print("\ngames picked (times picked, total corpus delta across those waves):")
        for g, deltas in sorted(seen.items(), key=lambda kv: -sum(kv[1])):
            print(f"  {g:8} picked {len(deltas):>2}x  {sum(deltas):+.3%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
