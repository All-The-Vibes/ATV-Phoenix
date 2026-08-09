"""CodeAct ARC-AGI-3 agent: executable Python is the action space (issue #177).

This replaces `vision_agent`, which emitted JSON plans and scored 1 of 40. That design
was the anti-pattern our own Prime Agent analysis identified as the weaker branch:

    CodeAct measured across 17 large language models that consolidating agent actions
    into executable Python outperforms JSON or text tool-call formats by up to 20
    percent higher success rate, because a fixed pre-defined tool scope cannot compose
    tools and cannot revise a prior action in light of a new observation.

That last clause is exactly what failed. A JSON plan is open-loop: 150 button presses
chosen in advance, executed blind. The environment reaches GAME_OVER roughly every 33
actions, so the agent spent most of its budget acting inside a restarted game it could
not see. It had no way to write "move right until you are under the target, then stop",
because a flat list cannot branch.

Here the model writes Python against a live environment handle and gets a persistent
namespace across turns, so it can:

* branch and loop on what it just observed, mid-plan
* define helper functions and reuse them next turn (Voyager's skill library)
* keep state in variables instead of restating it in prose

The environment API given to the model is deliberately small: `press`, `click`, `look`,
`grid`, `alive`, `levels`, and `reset`. Everything else it builds itself.

Usage::

    python -m evals.arc.codeact_agent --games sb26 --max-turns 20
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

from evals.arc.policies import CLICK_ACTION, frame_key  # noqa: E402
from evals.arc.render import data_url, palette_legend  # noqa: E402

ENDPOINT = os.environ.get(
    "AOAI_ENDPOINT", "https://ai-shyamsridhar-2008.cognitiveservices.azure.com/"
)
DEPLOYMENT = os.environ.get("AOAI_DEPLOYMENT", "gpt-5.6-sol")
TERMINAL = ("GameState.WIN", "GameState.GAME_OVER")

SYSTEM = """You are playing an unfamiliar video game by WRITING PYTHON.

You see the board as an image. Nobody tells you the rules. Work them out by running code
and reading what comes back. You are scored on levels completed.

Your code runs in a persistent namespace: variables and functions you define survive to
the next turn. Build up a toolkit as you learn the game.

API available to your code:

    press(n, times=1)   -> run action n, n times. Returns the observation dict.
    click(x, y)         -> click a cell (only if 6 is in ACTIONS).
    look()              -> observation dict WITHOUT acting.
    grid()              -> current board as a 64x64 numpy int array.
    alive()             -> False if the last action ended the game (you were reset).
    levels()            -> levels completed so far.
    reset()             -> restart from level 1.
    find(colour)        -> list of (y, x) cells of that colour.
    note(text)          -> write to your notes, which you keep seeing.

The observation dict has: levels, state, changed (did the board move), deaths_this_turn.

THIS IS THE WHOLE POINT: write CLOSED-LOOP code. Do not fire off blind sequences.

    # bad: blind, cannot react, dies and keeps going
    press(1, 150)

    # good: reacts to what it sees
    for _ in range(150):
        before = grid().copy()
        press(1)
        if not alive():
            note("action 1 kills me when the hazard is adjacent")
            break
        if (grid() == before).all():
            note("action 1 does nothing here; blocked")
            break

Write a full turn of play, not one experiment. Loop, branch, check `alive()`, back off
when something kills you, and try the next hypothesis in the SAME code block. You get few
turns, so each one should be a real attempt at progress.

Print anything you want to see next turn. Your stdout comes back to you.

Reply with ONLY a Python code block:

```python
# your code
```

No prose outside the block."""


class Env:
    """The handle the model's code drives. Counts actions and deaths honestly."""

    def __init__(self, env, frame):
        self._env = env
        self._frame = frame
        self._by_value = {int(a.value): a for a in env.action_space}
        self.actions = sorted(self._by_value)
        self.spent = 0
        self.deaths = 0
        self.best = 0
        self.notes: list[str] = []
        self._alive = True

    # ── internals ────────────────────────────────────────────────────────────────
    def _observe(self, changed=False):
        return {
            "levels": self._frame.levels_completed,
            "win_levels": self._frame.win_levels,
            "state": str(self._frame.state).replace("GameState.", ""),
            "changed": changed,
            "alive": self._alive,
        }

    def _step(self, action_value, data=None):
        try:
            nxt = (
                self._env.step(self._by_value[action_value], data)
                if data
                else self._env.step(self._by_value[action_value])
            )
        except Exception:
            return False
        if nxt is None:
            return False
        self.spent += 1
        changed = frame_key(nxt) != frame_key(self._frame)
        self._frame = nxt
        self.best = max(self.best, self._frame.levels_completed)
        if str(self._frame.state) in TERMINAL:
            if str(self._frame.state) == "GameState.GAME_OVER":
                self.deaths += 1
                self._alive = False
            self._frame = self._env.reset()
        return changed

    # ── surface the model uses ───────────────────────────────────────────────────
    def press(self, n, times=1):
        if n not in self._by_value:
            raise ValueError(f"action {n} not available; have {self.actions}")
        changed = False
        for _ in range(max(1, int(times))):
            self._alive = True
            changed = self._step(n) or changed
            if not self._alive:
                break
        return self._observe(changed)

    def click(self, x, y):
        if CLICK_ACTION not in self._by_value:
            raise ValueError("this game has no click action")
        self._alive = True
        changed = self._step(
            CLICK_ACTION, {"x": max(0, min(63, int(x))), "y": max(0, min(63, int(y)))}
        )
        return self._observe(changed)

    def look(self):
        return self._observe()

    def grid(self):
        arr = np.array(self._frame.frame, dtype=np.int8)
        return arr[0] if arr.ndim == 3 else arr

    def alive(self):
        return self._alive

    def levels(self):
        return self._frame.levels_completed

    def reset(self):
        self._frame = self._env.reset()
        self._alive = True
        return self._observe()

    def find(self, colour):
        ys, xs = np.where(self.grid() == int(colour))
        return list(zip(ys.tolist(), xs.tolist()))

    def note(self, text):
        self.notes.append(str(text)[:200])

    def frame(self):
        return self._frame


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
        azure_endpoint=ENDPOINT,
        azure_ad_token_provider=provider,
        api_version="2024-12-01-preview",
    )


def play(arc, game, client, deployment, max_turns, patience, action_cap) -> dict:
    raw = arc.make(game, include_frame_data=True)
    env = Env(raw, raw.reset())

    # Persistent namespace: this is the REPL the model keeps across turns.
    ns = {
        "press": env.press, "click": env.click, "look": env.look, "grid": env.grid,
        "alive": env.alive, "levels": env.levels, "reset": env.reset,
        "find": env.find, "note": env.note, "np": np,
    }

    tokens = 0
    stale = 0
    last_output = "(first turn; nothing run yet)"
    started = time.time()

    for turn in range(max_turns):
        before_levels = env.best
        before_spent = env.spent
        notes = "\n".join(f"- {n}" for n in env.notes[-25:]) or "(none yet)"

        content = [
            {
                "type": "text",
                "text": (
                    f"Game: {game}\n"
                    f"ACTIONS = {env.actions}"
                    f"{'  (6 is click(x,y))' if CLICK_ACTION in env.actions else ''}\n"
                    f"Levels: {env.best} of {env.frame().win_levels}\n"
                    f"Actions used: {env.spent} (soft budget {action_cap})\n"
                    f"Deaths so far: {env.deaths}\n"
                    f"Colours on screen: {palette_legend(env.frame().frame)}\n\n"
                    f"YOUR NOTES:\n{notes}\n\n"
                    f"OUTPUT FROM YOUR LAST CODE:\n{last_output}\n\n"
                    "Write this turn's code."
                ),
            },
            {"type": "text", "text": "Board now:"},
            {"type": "image_url", "image_url": {"url": data_url(env.frame().frame)}},
        ]

        try:
            reply = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": content},
                ],
                max_completion_tokens=16000,
            )
            tokens += reply.usage.total_tokens
            code = extract_code(reply.choices[0].message.content)
        except Exception as exc:
            last_output = f"model call failed: {type(exc).__name__}"
            continue

        if not code:
            last_output = "no python block came back; reply with ```python ... ``` only"
            continue

        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                exec(code, ns)  # noqa: S102 - executing model code is the design
            err = ""
        except Exception:
            err = traceback.format_exc(limit=3)

        out = buffer.getvalue()[-3000:]
        last_output = (out or "(no output printed)") + (f"\nERROR:\n{err}" if err else "")

        gained = env.best - before_levels
        stale = 0 if gained > 0 else stale + 1
        print(
            f"  {game} t{turn + 1}: acts={env.spent - before_spent} total={env.spent} "
            f"deaths={env.deaths} lv={env.best}/{env.frame().win_levels} tok={tokens}"
            f"{' ERR' if err else ''}",
            flush=True,
        )

        if env.best >= env.frame().win_levels:
            break
        if stale >= patience or env.spent >= action_cap:
            break

    return {
        "game": game,
        "agent": deployment,
        "levels_completed": env.best,
        "win_levels": env.frame().win_levels,
        "actions_spent": env.spent,
        "deaths": env.deaths,
        "tokens": tokens,
        "elapsed_s": round(time.time() - started, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="sb26")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-turns", type=int, default=20)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--action-cap", type=int, default=6000)
    ap.add_argument("--deployment", default=DEPLOYMENT)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import arc_agi

    arc = arc_agi.Arcade()
    available = [e.game_id.split("-")[0] for e in arc.get_environments()]
    games = available if args.all else [g.strip() for g in args.games.split(",") if g.strip()]

    client = make_client()
    started = time.time()
    runs = []
    for game in games:
        print(f"[{game}]", flush=True)
        runs.append(
            play(arc, game, client, args.deployment, args.max_turns, args.patience,
                 args.action_cap)
        )
        if args.out:
            Path(args.out).write_text(
                json.dumps(
                    {
                        "agent": args.deployment,
                        "auth": "managed_identity",
                        "action_space": "executable_python",
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
        r = runs[-1]
        print(f"  -> {r['levels_completed']}/{r['win_levels']}", flush=True)

    total = sum(r["levels_completed"] for r in runs)
    avail = sum(r["win_levels"] for r in runs)
    print(f"\nTOTAL {total}/{avail}  tokens={sum(r['tokens'] for r in runs):,}  "
          f"{round(time.time() - started, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
