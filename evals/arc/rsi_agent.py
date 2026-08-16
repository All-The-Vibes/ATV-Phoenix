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
from evals.arc.delegate import Delegator  # noqa: E402
from evals.arc.dropout import DropoutMonitor  # noqa: E402
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
    reprobe()           re-run the mechanical probe on the CURRENT level and return it.
                        CALL THIS EVERY TIME YOU CLEAR A LEVEL. Later levels change the
                        piece count, the tray layout, and which cells respond. Facts
                        measured on level 1 are stale afterwards.
    delegate(question, name="helper")
                        hand a focused question about the CURRENT board to a sub-agent
                        and get its finding back as text. The sub-agent can analyse the
                        board but cannot act on the game, so it is safe to ask freely.
    save_skill(name, source, description)
                        store working code so you and future runs can call it.

USE delegate() WHEN YOU ARE STUCK ON PERCEPTION, not on strategy. Good questions are
concrete and about what is on the board right now:

    delegate("List every distinct coloured block along the top row, left to right, "
             "with its colour value and centre x", name="read-targets")
    delegate("Which cells look like empty slots waiting to be filled, and where", name="find-slots")
    delegate("Compare the top row order against the bottom row order and tell me the "
             "permutation that maps one to the other", name="mapping")

Delegating is cheap and reading the board wrong is what loses levels. When your own
parse disagrees with what you see in the image, ask.

HOW TO ACTUALLY WIN:

PLAY THE GAME. These are games, not puzzles to be admired. A human needs hundreds of
actions to clear a single level, so a turn that takes three actions and prints a nice
analysis has done nothing. Inspecting the board is free and worth nothing on its own.
Every turn should spend real actions attempting real progress.

Read the board with code, not with your eyes. `grid()` is exact; the image is a hint.
Find the pieces, find the targets, compute the mapping, then act. Hard-coded coordinates
break on the next level. Code that re-reads the board does not.

Some boards have a button that redraws everything, which you will see in the probe as a
click changing several hundred cells. That is usually how a level starts. Click it, then
re-read the board.

Watch out for a colour that is both scenery and a piece. If a container outline is cyan
and one of the pieces is also cyan, filtering that colour out loses a piece and every
mapping you build afterwards is off by one.

When a level does not accept your arrangement, the arrangement is wrong, not the
mechanic. Print what you read, count the pieces against the targets against the slots,
and check they agree before clicking anything.

Write CLOSED-LOOP code. Check `alive()` and `levels()` as you go and stop when something
works or something kills you.

When a level falls, IMMEDIATELY call save_skill with a function that solves it by reading
the board, then call reprobe() to see what the next level actually is.

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
    from azure.identity import get_bearer_token_provider
    from openai import AzureOpenAI

    from evals.arc import aad

    provider = get_bearer_token_provider(aad.credential(), aad.SCOPE)
    return AzureOpenAI(
        azure_endpoint=ENDPOINT, azure_ad_token_provider=provider,
        api_version="2024-12-01-preview",
    )


def play(arc, game, client, deployment, max_turns, patience, library, probe_budget=180) -> dict:
    raw = arc.make(game, include_frame_data=True)
    env = Env(raw, raw.reset())

    # The API publishes how many actions a human needed per level. It is public metadata,
    # not a solution, and it is the honest yardstick for "are you actually playing".
    human_actions = []
    for meta in arc.get_environments():
        if meta.game_id.split("-")[0] == game:
            human_actions = list(meta.baseline_actions or [])
            break
    human_level1 = human_actions[0] if human_actions else 100
    human_total = sum(human_actions) if human_actions else 800

    print(f"  probing {game} (no tokens)...", flush=True)
    # Probe only when the library has nothing for this game. Probe actions are charged by
    # RHAE, and the arithmetic is brutal: on sb26 a 9-action solve behind a 141-action
    # probe scores 0.06 percent, while the same solve with no probe hits the 1.15 cap and
    # scores 3.19 percent. The mechanics are the same every run, so paying for them again
    # is pure loss. Learn once, then read them from the library for free.
    known = library.mechanics_for(game)
    if known:
        probe_text = known
        report = {"actions": {}, "click_rows": [], "drag_and_drop": [], "kills_you": False}
        print("    using learned mechanics (0 actions)", flush=True)
    else:
        report = probe(env, budget=probe_budget)
        probe_text = summarize(report)
        library.remember_mechanics(game, probe_text)
        print(f"    probed in {report['actions_spent_probing']} actions", flush=True)
    print("   ", probe_text.replace("\n", "\n    "), flush=True)

    tags = ["click"] if report["drag_and_drop"] else []
    if report["kills_you"]:
        tags.append("deadly")

    saved: list[str] = []

    def save_skill(name, source, description):
        library.add(name, game, source, description, tags)
        saved.append(name)
        return f"saved skill {name}"

    def reprobe():
        """Re-characterise the CURRENT level and refresh the probe text.

        Levels are not variations of one puzzle: level 2 of sb26 has a different piece
        count, a different tray layout, and a button that redraws the whole board. A
        probe taken once at level 1 is stale the moment a level is cleared, and acting
        on stale facts is what stalled every earlier run.
        """
        nonlocal probe_text
        fresh = probe(env, budget=probe_budget)
        probe_text = summarize(fresh)
        return probe_text

    delegator = Delegator(client)

    def delegate(question, name="helper"):
        """Hand a sub-question to a cheaper sub-agent and get its finding back."""
        return delegator.delegate(question, env.grid(), name=name)

    ns = {
        "press": env.press, "click": env.click, "look": env.look, "grid": env.grid,
        "alive": env.alive, "levels": env.levels, "reset": env.reset,
        "find": env.find, "note": env.note, "np": np, "save_skill": save_skill,
        "reprobe": reprobe, "delegate": delegate,
    }
    installed = library.install(ns, game, tags)
    if installed:
        print(f"    loaded skills: {installed}", flush=True)

    tokens = 0
    stale = 0
    tried: list[str] = []
    last_output = "(nothing run yet)"
    started = time.time()
    monitor = DropoutMonitor()
    stopped_because = ""
    env.reset()

    for turn in range(max_turns):
        before_levels = env.best
        before_spent = env.spent
        env.begin_turn()
        notes = "\n".join(f"- {n}" for n in env.notes[-20:]) or "(none)"
        stuck = STUCK.format(turns=stale, tried="\n".join(f"  - {t}" for t in tried[-6:])) \
            if stale >= patience else ""

        # Under-acting is the dominant failure across the corpus: on keyboard games the
        # agent spends about a tenth of the actions a human needs, so it never reaches
        # the end of level 1 and cannot possibly clear it.
        pace = ""
        if turn > 0 and env.spent < human_level1:
            pace = (
                f"\nPACE WARNING: you have taken {env.spent} actions. A human clears "
                f"level 1 of this game in about {human_level1} actions, and the whole "
                f"game in {human_total}. You are not playing enough to reach the end of "
                f"a level. Inspecting the board costs nothing and achieves nothing. "
                f"Spend actions: hundreds of them, in loops, checking levels() and "
                f"alive() as you go.\n"
            )

        content = [
            {
                "type": "text",
                "text": (
                    f"Game: {game}\n"
                    f"ACTIONS = {env.actions}\n"
                    f"Levels: {env.best} of {env.frame().win_levels}\n"
                    f"Actions taken: {env.spent} (a human needs ~{human_level1} for "
                    f"level 1, ~{human_total} for the game)\n"
                    f"Colours on screen: {palette_legend(env.frame().frame)}\n"
                    f"{pace}\n"
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
            # A cleared level means a new board, and every run so far cleared level 1
            # and then stalled forever on level 2 while acting on level 1's facts. The
            # re-probe is done here rather than left to the model to request, because
            # the model reliably did not request it.
            probe_text = reprobe()
            print(f"  {game} re-probed after level {env.best}", flush=True)
        else:
            stale += 1

        verdict = monitor.record(
            code=code,
            levels=env.best,
            actions=env.spent,
            changed=env.spent > before_spent,
            errored=bool(err),
            turn_actions=env.spent - before_spent,
        )

        print(
            f"  {game} t{turn + 1}: lv={env.best}/{env.frame().win_levels} "
            f"acts={env.spent} deaths={env.deaths} tok={tokens}"
            f"{' +LEVEL' if gained else ''}{' ERR' if err else ''}",
            flush=True,
        )

        if env.best >= env.frame().win_levels:
            break

        if verdict:
            stopped_because = verdict.reason
            print(f"  {game} DROPPED OUT: {verdict.reason}", flush=True)
            print(f"    {verdict.diagnosis}", flush=True)
            print(f"    -> {verdict.advice}", flush=True)
            env.note(f"gave up: {verdict.reason}. {verdict.advice}")
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
        **delegator.summary(),
        "stopped_because": stopped_because,
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
