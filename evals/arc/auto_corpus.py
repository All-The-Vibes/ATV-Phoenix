"""The corpus runs itself: pick by expected value, score, repeat, forever.

Waves were being chosen by hand and by intuition -- "these three look weak" -- which
is how r20 came to spend three runs on never-revisited games at the exact moment the
data said to do the opposite.

The data: actions to clear level 1, same game, across every run on disk.

  game   runs   min    max   spread   human_lv1
  tr87      9    32   1265    39.5x      54
  cd82     18    16    328    20.5x      55
  r11l      6     8    147    18.4x      22
  sb26     36     9    139    15.4x      18

Two facts follow. The agent's MINIMUM usually beats the human baseline -- cd82 16
against 55, sb26 9 against 18 -- so it is not incapable of human-or-better efficiency.
And it cannot do it reliably, with a 10-40x spread on the same game.

Scoring is max-of-runs. A high-variance game under a max operator is a draw from a
long tail, so the expected best keeps improving with N, and re-running a game the
agent has already beaten its own average on is worth more than a first look at a new
one. That is an argument from the measured distribution rather than from hope.

So this ranks games by expected gain instead of by feel:

    EV = headroom * P(a draw lands above the current best)

`headroom` is what the game could still contribute to the corpus (its per-game share
minus what it currently scores). The probability term is estimated from the spread of
that game's own history: a game whose runs vary 20x has a real chance of a tail draw,
a game whose runs are tightly clustered near its best does not.

Runs forever. Each wave: pick, launch, wait, score, record, repeat. Everything lands
in a JSONL so the improvement over time is a measurement and not a memory.

    python evals/arc/auto_corpus.py --waves 0 --concurrency 3     # 0 = forever
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.arc.rhae import load_baselines, score_run  # noqa: E402

RESULTS = ROOT / "eval" / "arc-results"
LEDGER = RESULTS / "auto-corpus-ledger.jsonl"
STATE = RESULTS / "auto-corpus-state.json"


def all_runs(baselines: dict) -> dict[str, list[dict]]:
    """Every scorable run on disk, grouped by game."""
    out: dict[str, list[dict]] = {}
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
            out.setdefault(game, []).append(run)
    return out


def picks_so_far() -> dict[str, int]:
    """How often the loop has already spent a run on each game, from the ledger.

    Without this the ranker is pure exploitation with no memory: two waves at lf52 and
    g50t returned nothing, the scores were unchanged, so the ranking was identical and
    it would have picked the same three games forever.
    """
    counts: dict[str, int] = {}
    if not LEDGER.exists():
        return counts
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") != "wave":
            continue
        for game in row.get("games") or []:
            counts[game] = counts.get(game, 0) + 1
    return counts


def rank(baselines: dict) -> list[tuple[float, str, dict]]:
    """Games ordered by expected gain from one more run."""
    runs = all_runs(baselines)
    attempts = picks_so_far()
    n_games = len(baselines) or 1
    share = 1.0 / n_games            # what one perfect game is worth to the corpus
    ranked = []
    for game, rs in runs.items():
        scores = sorted(r["_score"] for r in rs)
        best = scores[-1]
        levels = max(r["levels_completed"] for r in rs)

        # THE DEPTH WE HAVE ALREADY PROVEN, not the depth of the best-scoring run.
        # These are different numbers and the difference is free score. r11l has
        # cleared all 6 of its levels (auto3, 512 actions) and scores 51.19%, while a
        # 5-level run scores 65.81% and is therefore the one on the board -- a slow
        # deep clear loses to a fast shallow one under max-of-runs. Five games are in
        # this state: g50t, ls20, r11l, sp80, tu93.
        #
        # That matters for ranking because a level already cleared ONCE is not a
        # gamble. The agent has demonstrated it can reach level 6 of r11l; it simply
        # did it slowly. Ranking by the best-scoring run's depth hides that entirely
        # and treats r11l as a 5-level game with a speculative 6th.
        #
        # Measured: playing the five proven-deep clears at the cap is worth +4.40pp,
        # r11l alone 1.97pp -- and none of it requires beating a level we have never
        # beaten.
        proven_levels = levels

        # HEADROOM IS BOUNDED BY LEVELS CLEARED, NOT BY 100%. The first version used
        # (1 - best) * share, which assumes any game could reach a perfect score. It
        # cannot: RHAE caps a level at 1.15 and weights it by index, so a game with
        # `levels` of `total` cleared can never exceed sum(1..levels)/sum(1..total)
        # * 1.15 however fast it plays.
        #
        # That error was not academic. lf52 at 1 of 10 levels has a ceiling of 2.09%
        # and was ALREADY scoring 2.09%; g50t at 1 of 7 has a ceiling of 4.11% and was
        # scoring 4.11%. Both had exactly zero efficiency headroom, and the ranker sent
        # six runs at them across two waves for no possible gain. One of those runs
        # cleared lf52's level 1 in 8 actions against a human's 32 -- four times faster
        # -- and scored the same 2.09%, because the level was already at the cap.
        #
        # So the room a run can actually win is the distance to the ceiling AT THE
        # LEVELS ALREADY CLEARED, plus what the next level would add if it falls.
        n_levels = len(baselines[game])
        weight_sum = sum(range(1, n_levels + 1)) or 1
        ceiling_now = sum(range(1, proven_levels + 1)) / weight_sum * 1.15
        efficiency_room = max(0.0, ceiling_now - best)
        next_level_room = (((proven_levels + 1) / weight_sum * 1.15)
                           if proven_levels < n_levels else 0.0)
        headroom = (efficiency_room + next_level_room) * share

        # Spread of this game's OWN level-1 discovery cost, as the variance proxy.
        firsts = [r.get("level_actions", [None])[0] for r in rs
                  if r.get("level_actions")]
        firsts = [f for f in firsts if f]
        spread = (max(firsts) / max(1, min(firsts))) if len(firsts) >= 2 else 1.0

        # A draw beats the current best when the distribution is wide and the current
        # best is not already an outlier. Both terms are bounded and deliberately
        # crude -- this orders games, it does not predict a score.
        width = min(1.0, math.log10(max(1.0, spread)) / 1.6)   # 40x -> ~1.0
        room = 1.0 - min(1.0, best)                            # near the cap -> ~0
        p = max(0.02, width * room)

        # A game picked repeatedly that never pays is evidence the model is wrong about
        # it, and the model has no way to learn that from the scores alone -- two waves
        # at lf52 and g50t returned nothing and the ranking was identical afterwards,
        # so it would have picked them forever. Decaying by attempts is the cheapest
        # honest correction: keep exploiting a wide game, but let an unproductive one
        # fall behind an untried one rather than blocking it out permanently.
        ev = headroom * p / (1.0 + 0.5 * attempts.get(game, 0))
        ranked.append((ev, game, {
            "best": round(best, 4), "runs": len(rs),
            "spread": round(spread, 1), "p": round(p, 3),
            "headroom_pp": round(headroom * 100, 3),
            "levels": levels, "of": n_levels,
            "eff_room": round(efficiency_room, 4),
            "tried": attempts.get(game, 0),
        }))
    ranked.sort(reverse=True)
    return ranked


def corpus_now(baselines: dict) -> tuple[float, int]:
    runs = all_runs(baselines)
    total = 0.0
    levels = 0
    for game, rs in runs.items():
        best = max(rs, key=lambda r: r["_score"])
        total += best["_score"]
        levels += best["levels_completed"]
    return total / max(1, len(baselines)), levels


def agents_alive() -> int:
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
           "Where-Object { $_.CommandLine -like '*codeact_agent*' } | "
           "Measure-Object | Select-Object -ExpandProperty Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, text=True, timeout=90)
        return int((out.stdout or "0").strip() or 0)
    except Exception:
        return 10 ** 6      # unknowable is not zero; never admit a wave on a guess


def record(entry: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--waves", type=int, default=0, help="0 runs forever")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=120)
    ap.add_argument("--patience", type=int, default=90)
    ap.add_argument("--tag-prefix", default="auto")
    args = ap.parse_args()

    baselines = load_baselines()
    wave = 0
    start_corpus, start_levels = corpus_now(baselines)
    print(f"start: corpus {start_corpus:.2%}, {start_levels} levels", flush=True)
    record({"event": "start", "at": datetime.now(timezone.utc).isoformat(),
            "corpus": start_corpus, "levels": start_levels})

    while args.waves == 0 or wave < args.waves:
        while agents_alive() > 0:
            print("  waiting for the machine to clear...", flush=True)
            time.sleep(120)

        wave += 1
        tag = f"{args.tag_prefix}{wave}"
        ranked = rank(baselines)
        picks = [g for _, g, _ in ranked[:args.concurrency]]
        detail = {g: d for _, g, d in ranked[:args.concurrency]}
        before, before_levels = corpus_now(baselines)
        print(f"\n=== wave {wave} ({tag}) corpus {before:.2%} ===", flush=True)
        for _, g, d in ranked[:args.concurrency]:
            print(f"    {g}: best={d['best']:.2%} spread={d['spread']}x "
                  f"headroom={d['headroom_pp']:.2f}pp p={d['p']}", flush=True)

        log = RESULTS / f"queue-{tag}.log"
        cmd = [sys.executable, "evals/arc/queue_runner.py",
               "--games", ",".join(picks), "--tag", tag,
               "--concurrency", str(args.concurrency),
               "--max-turns", str(args.max_turns),
               "--patience", str(args.patience)]
        t0 = time.time()
        with log.open("w", encoding="utf-8") as fh:
            subprocess.run(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
        elapsed = round(time.time() - t0)

        after, after_levels = corpus_now(baselines)
        gained = after - before
        print(f"=== wave {wave} done in {elapsed}s: corpus {before:.2%} -> {after:.2%} "
              f"({gained:+.2%}), levels {before_levels} -> {after_levels}", flush=True)
        record({
            "event": "wave", "wave": wave, "tag": tag,
            "at": datetime.now(timezone.utc).isoformat(),
            "games": picks, "why": detail, "elapsed_s": elapsed,
            "corpus_before": before, "corpus_after": after, "delta": gained,
            "levels_before": before_levels, "levels_after": after_levels,
        })
        STATE.write_text(json.dumps({
            "wave": wave, "tag": tag, "corpus": after, "levels": after_levels,
            "since_start_pp": round((after - start_corpus) * 100, 3),
            "updated": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
