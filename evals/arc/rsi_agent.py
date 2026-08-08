"""RSI ARC agent: probe, act in code, keep what works, notice when stuck (issue #177).

Built from four measured failures, in the order they were found today:

1. A text sketch of a 64x64 grid on a spatial benchmark. The agent was blind.
2. Silent reset on death, so the model planned inside a restarted game it could not see.
3. JSON plans, which our own Prime Agent analysis had already identified as the weaker
   branch: a fixed tool scope "cannot revise a prior action in light of a new
   observation". That is precisely how it failed.
4. No memory, so every turn re-derived the rules from scratch.

What this does instead:

* **Probe before prompting.** `prober` characterises the game mechanically and costs no
  tokens. On `sb26` it discovers drag-and-drop unaided, which is the fact that turns an
  unsolvable board into a nine-action solve.
* **Executable Python as the action space,** with a persistent namespace.
* **A skill library.** Working code is saved, reloaded, and offered on later levels and
  other games.
* **Stuck detection.** Repeating a failing approach is the failure mode of every run so
  far, so after `patience` turns without a level the agent is told it is stuck, shown
  what it already tried, and required to change strategy.

Usage::

    python -m evals.arc.rsi_agent --games sb26 --max-turns 20
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.arc.codeact_agent import Env  # noqa: E402
from evals.arc.prober import probe, summarize  # noqa: E402
from evals.arc.render import data_url, palette_legend  # noqa: E402
from evals.arc.skills import SkillLibrary  # noqa: E402

ENDPOINT = os.environ.get(
    "AOAI_ENDPOINT", "https://ai-shyamsridhar-2008.cognitiveservices.azure.com/"
)
DEPLOYMENT = os.environ.get("AOAI_DEPLOYMENT", "gpt-5.6-sol")

SYSTEM = """You are beating an unfamiliar video game by WRITING PYTHON.

You are given a mechanical probe of the game: measured facts about what each action does,
which cells respond to clicks, and whether picking something up then clicking elsewhere
moves it. Those facts were measured, not guessed. TRUST THEM over anything you infer from
the picture.

Your code runs in a persistent namespace. Functions you define survive to the next turn.

API:
    press(n, times=1)   run action n. Returns {levels, state, changed, alive}.
    click(x, y)         click a cell.
    look()              observe without acting.
    grid()              64x64 numpy int array of the board.
    alive()             False if the last action ended the game.
    levels()            levels completed.
    reset()             restart from level 1.
    find(colour)        [(y, x), ...] cells of that colour.
    note(text)          write to your notes.
    save_skill(name, source, description)
                        store working code so you and future runs can call it.

HOW TO ACTUALLY WIN:

Read the board with code, not with your eyes. `grid()` is exact; the image is a hint.
Find the pieces, find the targets, compute the mapping, then act. Hard-coded coordinates
break on the next level. Code that re-reads the board does not.

Write CLOSED-LOOP code. Check `alive()` and `levels()` as you go and stop when something
works or something kills you.

When a level falls, IMMEDIATELY call save_skill with a function that solves it by reading
the board. The next level is usually the same game, bigger.

Reply with ONLY a Python block:

```python
# your code
```"""

STUCK = """
YOU ARE STUCK. {turns} turns, no new level. What you have tried:
{tried}

Do NOT repeat any of it. Change something structural:
  - Re-read the board with grid() and print what you find; your model of it may be wrong.
  - Try an action you have been ignoring.
  - If drag-and-drop is confirmed, the target order is probably encoded somewhere you
    have not parsed. Print the distinct colours per row band and look again.
  - Try a deliberately wrong arrangement and read how the board rejects it. A rejection
    tells you what the checker is checking.
"""


def extract_code(text: str) -> str:
    if not text:
        return ""
    fence = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return fence.group(1).strip() if fence else ""


def make_client():
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_endpoint=ENDPOINT, azure_ad_token_provider=provider,
        api_version="2024-12-01-preview",
    )


def play(arc, game, client, deployment, max_turns, patience, library) -> dict:
    raw = arc.make(game, include_frame_data=True)
    env = Env(raw, raw.reset())

    print(f"  probing {game} (no tokens)...", flush=True)
    report = probe(env, click_step=6)
    probe_text = summarize(report)
    print("   ", probe_text.replace("\n", "\n    "), flush=True)

    tags = ["click"] if report["drag_and_drop"] else []
    if report["kills_you"]:
        tags.append("deadly")

    saved: list[str] = []

    def save_skill(name, source, description):
        library.add(name, game, source, description, tags)
        saved.append(name)
        return f"saved skill {name}"

    ns = {
        "press": env.press, "click": env.click, "look": env.look, "grid": env.grid,
        "alive": env.alive, "levels": env.levels, "reset": env.reset,
        "find": env.find, "note": env.note, "np": np, "save_skill": save_skill,
    }
    installed = library.install(ns, game, tags)
    if installed:
        print(f"    loaded skills: {installed}", flush=True)

    tokens = 0
    stale = 0
    tried: list[str] = []
    last_output = "(nothing run yet)"
    started = time.time()
    env.reset()

    for turn in range(max_turns):
        before_levels = env.best
        notes = "\n".join(f"- {n}" for n in env.notes[-20:]) or "(none)"
        stuck = STUCK.format(turns=stale, tried="\n".join(f"  - {t}" for t in tried[-6:])) \
            if stale >= patience else ""

        content = [
            {
                "type": "text",
                "text": (
                    f"Game: {game}\n"
                    f"ACTIONS = {env.actions}\n"
                    f"Levels: {env.best} of {env.frame().win_levels}\n"
                    f"Colours on screen: {palette_legend(env.frame().frame)}\n\n"
                    f"{probe_text}\n\n"
                    f"SKILLS YOU CAN CALL:\n{library.describe(game, tags)}\n\n"
                    f"YOUR NOTES:\n{notes}\n\n"
                    f"OUTPUT FROM YOUR LAST CODE:\n{last_output}\n"
                    f"{stuck}\n"
                    "Write this turn's code."
                ),
            },
            {"type": "text", "text": "Board now:"},
            {"type": "image_url", "image_url": {"url": data_url(env.frame().frame)}},
        ]

        try:
            reply = client.chat.completions.create(
                model=deployment,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": content}],
                max_completion_tokens=16000,
            )
            tokens += reply.usage.total_tokens
            code = extract_code(reply.choices[0].message.content)
        except Exception as exc:
            last_output = f"model call failed: {type(exc).__name__}"
            continue

        if not code:
            last_output = "no python block; reply with ```python ... ``` only"
            continue

        tried.append(code.strip().splitlines()[0][:90] if code.strip() else "(empty)")

        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                exec(code, ns)  # noqa: S102 - executing model code is the design
            err = ""
        except Exception:
            err = traceback.format_exc(limit=3)

        out = buffer.getvalue()[-2500:]
        last_output = (out or "(no output)") + (f"\nERROR:\n{err}" if err else "")

        gained = env.best - before_levels
        if gained > 0:
            stale = 0
            for name in saved:
                library.record(name, won=True)
        else:
            stale += 1

        print(
            f"  {game} t{turn + 1}: lv={env.best}/{env.frame().win_levels} "
            f"acts={env.spent} deaths={env.deaths} tok={tokens}"
            f"{' +LEVEL' if gained else ''}{' ERR' if err else ''}",
            flush=True,
        )

        if env.best >= env.frame().win_levels:
            break
        if stale >= patience * 2:
            break

    for name in saved:
        if env.best == 0:
            library.record(name, won=False)

    return {
        "game": game,
        "agent": deployment,
        "levels_completed": env.best,
        "win_levels": env.frame().win_levels,
        "actions_spent": env.spent,
        "deaths": env.deaths,
        "tokens": tokens,
        "skills_saved": saved,
        "elapsed_s": round(time.time() - started, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="sb26")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-turns", type=int, default=18)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--deployment", default=DEPLOYMENT)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import arc_agi

    arc = arc_agi.Arcade()
    available = [e.game_id.split("-")[0] for e in arc.get_environments()]
    games = available if args.all else [g.strip() for g in args.games.split(",") if g.strip()]

    client = make_client()
    library = SkillLibrary()
    started = time.time()
    runs = []

    for game in games:
        print(f"[{game}]", flush=True)
        runs.append(play(arc, game, client, args.deployment, args.max_turns,
                         args.patience, library))
        r = runs[-1]
        print(f"  -> {r['levels_completed']}/{r['win_levels']}\n", flush=True)
        if args.out:
            Path(args.out).write_text(
                json.dumps(
                    {
                        "agent": args.deployment,
                        "auth": "managed_identity",
                        "action_space": "executable_python",
                        "probe": "mechanical",
                        "skill_library": True,
                        "games": len(runs),
                        "levels_completed": sum(r["levels_completed"] for r in runs),
                        "levels_available": sum(r["win_levels"] for r in runs),
                        "tokens": sum(r["tokens"] for r in runs),
                        "wall_clock_s": round(time.time() - started, 1),
                        "runs": runs,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    total = sum(r["levels_completed"] for r in runs)
    avail = sum(r["win_levels"] for r in runs)
    print(f"TOTAL {total}/{avail}  tokens={sum(r['tokens'] for r in runs):,}  "
          f"{round(time.time() - started, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
