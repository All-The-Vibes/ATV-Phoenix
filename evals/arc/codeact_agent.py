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
`grid`, `alive`, `levels`, `reset`, plus `objects`/`board`, which return the board's
discrete blobs computed from the pixels for zero game actions. Everything else it builds
itself.

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

from evals.arc.boardread import describe as describe_board  # noqa: E402
from evals.arc.boardread import diff as diff_board  # noqa: E402
from evals.arc.boardread import objects as board_objects  # noqa: E402
from evals.arc.frames import parse as frame_parse  # noqa: E402
from evals.arc.frames import plan as frame_plan  # noqa: E402
from evals.arc.phoenix_loop import PhoenixLoop  # noqa: E402
from evals.arc.policies import CLICK_ACTION, frame_key  # noqa: E402
from evals.arc.render import data_url, palette_legend  # noqa: E402
from evals.arc.rule_gate import (  # noqa: E402
    RuleGate,
    placements_from_clicks,
    rounds_from_clicks,
)
from evals.arc.skills import SkillLibrary  # noqa: E402

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
    objects()           -> EXACT list of every discrete blob on the board right now:
                           [{colour, cx, cy, x0, x1, y0, y1, px}, ...]. Costs NOTHING.
    board()             -> the same thing as readable text, grouped into rows.
    layout()            -> the board split by SHAPE alone into {frames, pads, clues,
                           tray, clue_structure}, or None if it is not drawn that way.
                           FREE.
                           layout()["clue_structure"] describes the SHAPE OF THE CLUE ROW,
                           because the row is not always one ring per pad. It reports
                           {flat, colours, block, at, reduced}: `flat` is False when the
                           row is longer than the pad count, `block` is the run of colours
                           that repeats, `at` where its occurrences start, and `reduced`
                           is the row with each occurrence replaced by a single None.
                           Measured on level 5: nine rings over eight pads read as
                           colours=[6,14,8,8,14,8,8,11,15], block=[14,8,8],
                           reduced=[6,None,None,11,15].
                           It tells you the row's SHAPE, not its meaning. Which pads the
                           reduced row addresses, which pads take the block, and what
                           colour belongs on a None are yours to work out -- and the tray
                           is the lever, because it holds exactly one piece per pad, so
                           whatever it has left over after the spelled-out colours are
                           accounted for is what the holes take.
    note(text)          -> write to your notes, which you keep seeing.
    sense(claim, ok)    -> record one trial of a belief. FREE.
    accept(claim)       -> {'ok': bool, 'reason': str}: is that belief actually proven?
    propose(rule)       -> test a rule against EVERY level you have already cleared. FREE.
    refuted(order)      -> has this exact placement order already failed here? FREE.

YOUR DELIVERABLE IS A RULE, NOT A SEQUENCE OF CLICKS. Write a function rule(layout) that
DERIVES the placements from the board it is given, and call propose(rule). It is replayed
against every level you have already solved, for zero actions, and refused if it only fits
the board in front of you.

This is the difference between winning and stalling, measured. A previous run cleared a
level by writing this:

    assignment = [(12, (22, 22)), (15, (28, 22)), (6, (40, 22)), ...]

That is a lookup table. It cleared that one board and was worth nothing on the next, so
cost per level went 9 -> 16 -> 38 -> 126 actions and the run died. A rule that reads the
board survives every level; a table has to be rebuilt each time, more expensively.

So when you find something that works, ask WHY it worked in terms of what is drawn on the
board, write that as rule(layout), and propose() it. If it fails an earlier level, that
failure is the most useful thing you will see all run: it tells you exactly which part of
your understanding is a coincidence.

PASSING propose() IS NECESSARY, NOT SUFFICIENT. Measured: on one level the agent proposed
twelve different orders, all twelve reproduced every solved level and were accepted, and
all twelve were refused by the board. The solved levels could not tell them apart. When
that happens the solved levels are exhausted as evidence and only the board can decide, so
stop refining a theory they already agree with and go test something they cannot rule on.
Read the REFUTED list before you spend actions: if every assignment you have tried agrees
on where some colour goes, that agreement is an assumption you have never questioned, not
a fact you established. Deliberately try one that breaks it.

TEST SEVERAL CANDIDATES IN ONE TURN. Placing a seven-piece board, submitting, and undoing
back costs about 25 actions, and you may spend 120 in a turn -- so four distinct
assignments fit in the turn you are writing now. Measured: a run stuck on one level tested
eight assignments across twelve turns and finished with 250 of its 8000 actions unspent.
It was not short of budget, it was spending a turn's worth of thinking on a single guess.
When the solved levels can no longer tell your candidates apart, stop ranking them and
submit several: a loop that tries four and reports which cleared is worth more than a turn
of argument about which one deserves the try.

SENSE AND ACCEPT ARE THE POINT. accept() refuses any claim you have never seen FAIL,
because a claim that was only ever confirmed is a guess you got attached to. Every
measured disaster on this benchmark came from skipping that: one run believed an action
advanced a timer, pressed it 56 times and died, when a single press would have shown the
claim was false. Another spent 2,075 actions in one turn defending an untested theory.

So: before you spend more than about ten actions on a theory, spend ONE to try to break
it. Write down what you expect to see, do the cheapest thing that would show you are
wrong, and call sense(claim, it_matched). You want to be wrong early, when it is cheap.

FIRST-CONTACT DISCOVERY, on a game you have not played before. This costs roughly one
action per available action and it is the best-value spend on the board:

    for a in ACTIONS:                 # what does each action actually DO?
        before = grid().copy()
        press(a)
        sense(f"action {a} changes the board", not (grid() == before).all())
        note(f"action {a}: changed={not (grid() == before).all()} alive={alive()}")

An action that changes nothing visible is usually the one that submits, commits or
confirms, and that is the action every stuck run failed to find. If you have arranged the
board the way you believe it should be and nothing happened, try each inert action ONCE
before you conclude your arrangement is wrong. Rebuilding an arrangement that was already
correct is the single most expensive mistake available to you.

WHEN A GUESS IS CHEAP, GUESS AND READ THE ANSWER. Check what a wrong attempt actually
costs before assuming it is fatal: submit a deliberate near-miss once and diff the board.
If the game just says no, an attempt is a few actions and you can afford several reasoned
ones. If it kills you, it is not.

READ THE ORDER OFF THE BOARD. When a puzzle needs things done in a particular sequence,
the sequence is usually DRAWN: boxes group items, and a line or a mark of one group's
colour appearing inside another group is a link telling you to jump there and come back.
Follow those links instead of guessing the order. Reading order is the fallback, not the
first answer, and permuting is never the answer.

layout() gives you the board split by shape alone, with no colour or row hardcoded: which
blobs are frames, which are pads, which are clues, which are tray pieces. Working out what
the clues MEAN is yours to do. Derive the reading, then treat it as a hypothesis like any
other: submit it ONCE and sense() the result.

USE objects() INSTEAD OF WRITING YOUR OWN COLOUR FILTER. Every run that lost a level lost
it by hand-rolling a parser like "scan rows 54..64 for colours not in (0,4,5,14,15)",
which silently drops a piece the moment a level reuses a colour differently. objects() is
computed from the pixels with no assumptions and no hardcoded colour list.

COUNT BEFORE YOU ACT. Print the number of pieces and the number of destinations and check
they match. The single measured level-2 failure was six pieces placed into seven slots:
the parser had dropped one, nothing counted, and the level silently refused to clear.
Distinguish pieces from scenery by SIZE and REPETITION, never by colour value: pieces are
several same-sized blobs; a frame or outline is one big blob spanning the whole region.

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

If your parse disagrees with itself, DO NOT freeze and print "mismatch, no action". A turn
that spends zero actions learns nothing and you will meet the same wall next turn. Re-read
with objects(), which is ground truth, believe it over whatever you derived earlier, and
act on it.

NEVER SEARCH BY BRUTE FORCE. Do not loop over permutations, orderings or candidate
arrangements. This was measured: one turn tried 25 orderings for 2075 actions and 25
deaths, another tried 144 arrangements for 1012 actions, and neither found anything. RHAE
squares your action count, so a search that eventually succeeds still scores near zero,
and every failed attempt runs the clock out and kills you. If your first, reasoned
arrangement is rejected, that is INFORMATION: something about your model of the rule is
wrong. Re-read the board, work out what distinguishes the arrangement the game wanted
from the one you built, and make ONE more reasoned attempt. Ten thought-out attempts beat
ten thousand blind ones, and they are what the score rewards.

Print anything you want to see next turn. Your stdout comes back to you.

Reply with ONLY a Python code block:

```python
# your code
```

No prose outside the block."""


class TurnBudgetExhausted(RuntimeError):
    """Raised inside model code when one turn has spent its action allowance.

    Two runs wrote unbounded loops and spent 111,499 and 90,527 actions on a single
    game while clearing nothing. A loop with no exit is not play, and letting it run
    costs the rest of the corpus. The exception surfaces to the agent as a caught
    error, so the next turn is told what happened rather than silently truncated.
    """


class LevelCleared(RuntimeError):
    """Raised the instant `levels_completed` increments.

    A level transition emits no state change: `next_level` flips an internal flag and
    leaves the game NOT_FINISHED, so the board silently becomes a different level
    mid-loop. The model's in-flight code must not keep running level-N coordinates and
    helpers against level N+1's board, so we cut the loop and tell it what happened.
    """


class StallDetected(RuntimeError):
    """Raised after N consecutive actions that left the board unchanged.

    RHAE squares the action count, so an action that does not change the board has
    strictly negative value: it cannot advance the level and it shrinks the score of
    every level still to come. Grinding is worse than stopping and rethinking.
    """


class Env:
    """The handle the model's code drives. Counts actions and deaths honestly."""

    def __init__(self, env, frame, turn_action_cap: int = 4000, inert_limit: int = 40,
                 death_limit: int = 3):
        self._env = env
        self._frame = frame
        self._by_value = {int(a.value): a for a in env.action_space}
        self.actions = sorted(self._by_value)
        self.spent = 0
        self.deaths = 0
        self.best = 0
        self.notes: list[str] = []
        self._alive = True
        self._turn_action_cap = turn_action_cap
        self._turn_spent = 0
        self.inert_limit = inert_limit
        self.death_limit = death_limit
        self.level_actions: list[int] = []
        self.click_log: list[tuple[int, int, int]] = []
        # The board as the current level first presented it, for the rule gate. It cannot
        # be captured when the level clears: at that instant the board still shows the
        # level just solved, with every piece placed and the tray EMPTY, and it only
        # advances on the next action. Snapshotting there banked an empty tray and threw
        # away four cleared levels. So it is captured from the clicks themselves, keeping
        # whichever board had the fullest tray -- placements only ever remove pieces from
        # the tray, so the fullest one is the level as it was handed to the agent.
        self.level_grid = None
        self._level_tray = -1
        self._level_mark = 0
        self._inert = 0
        self.level_just_changed = False
        self.game_won = False
        self.deaths_this_turn = 0

    def begin_turn(self) -> None:
        self._turn_spent = 0
        self.deaths_this_turn = 0        # alive() answers "did the last action kill me", not "have I ever died". It was
        # a latch: set False on death and cleared only by an explicit reset(), even
        # though the death handler below already resets the frame and the game is
        # immediately playable again. The prompt teaches `if not alive(): break`, so
        # after the first death every guarded block in the agent's code became a silent
        # no-op. That is measured, not theoretical: turns 17-22 of the 4/8 run each
        # produced zero output and zero level change because their `if alive():` bodies
        # never ran. Clearing it per turn restores the idiom the prompt asks for.
        self._alive = True

    @property
    def turn_spent(self) -> int:
        return self._turn_spent

    # ── internals ────────────────────────────────────────────────────────────────
    def _observe(self, changed=False):
        return {
            "levels": self._frame.levels_completed,
            "win_levels": self._frame.win_levels,
            "state": str(self._frame.state).replace("GameState.", ""),
            "changed": changed,
            "alive": self._alive,
            "deaths_this_turn": self.deaths_this_turn,
            "level_actions": list(self.level_actions),
            "level_just_changed": self.level_just_changed,
        }

    def _step(self, action_value, data=None):
        if self._turn_spent >= self._turn_action_cap:
            raise TurnBudgetExhausted(
                f"this turn already spent {self._turn_spent} actions. You are in a loop "
                f"with no exit. Check levels() and alive() inside your loops and break."
            )
        try:
            nxt = (
                self._env.step(self._by_value[action_value], data)
                if data
                else self._env.step(self._by_value[action_value])
            )
        except TurnBudgetExhausted:
            raise
        except Exception:
            return False
        if nxt is None:
            return False
        before_levels = self._frame.levels_completed
        self.spent += 1
        self._turn_spent += 1
        changed = frame_key(nxt) != frame_key(self._frame)
        self._frame = nxt
        self.best = max(self.best, self._frame.levels_completed)

        if self._frame.levels_completed > before_levels:
            actions = self.spent - self._level_mark
            self.level_actions.append(actions)
            self._level_mark = self.spent
            self.level_just_changed = True
            self._inert = 0
            raise LevelCleared(
                f"LEVEL {self._frame.levels_completed} CLEARED in {actions} actions. "
                "The board below is a DIFFERENT level. Coordinates and helper functions "
                "from the previous level are presumed INVALID until you re-verify them."
            )

        if changed:
            self._inert = 0
        else:
            self._inert += 1
            if self._inert >= self.inert_limit:
                limit = self._inert
                self._inert = 0
                raise StallDetected(
                    f"the board has not changed in {limit} consecutive actions. Whatever "
                    "you are repeating does not affect this level. Every wasted action is "
                    "squared against your score, so stop and try a structurally different "
                    "approach: a different action, a different target, or a re-read of the "
                    "board to check what your model of the game got wrong."
                )

        if str(self._frame.state) in TERMINAL:
            if str(self._frame.state) == "GameState.WIN":
                # WIN fires only when the LAST level is beaten: the whole game is over.
                # Resetting here would throw away the finished run and restart level 1.
                self.game_won = True
            else:
                self.deaths += 1
                self.deaths_this_turn += 1
                self._alive = False
                self._frame = self._env.reset()
                # A death here is the row-53 timer running out, and the measured failure
                # mode is a search loop that keeps dying without noticing. Each retry
                # costs a full clock AND every action it spent, both squared against the
                # score. Stop the loop from inside rather than letting it run to the
                # 4000-action cap, which is what turned one bad turn into 2075 actions.
                if self.deaths_this_turn >= self.death_limit:
                    raise StallDetected(
                        f"you have died {self.deaths_this_turn} times in this single "
                        f"turn. The row-53 bar is a countdown and you are running it out "
                        f"repeatedly. Whatever you are searching, the answer is not in "
                        f"that search. Stop, re-read the board with objects(), and work "
                        f"out the rule instead of trying more arrangements."
                    )
        return changed

    # ── surface the model uses ───────────────────────────────────────────────────
    def press(self, n, times=1):
        if n not in self._by_value:
            raise ValueError(f"action {n} not available; have {self.actions}")
        changed = False
        # Set once, outside the loop: setting it per iteration erased a death that
        # happened on an earlier press, so `alive()` lied and the loop kept going.
        self._alive = True
        for _ in range(max(1, int(times))):
            changed = self._step(n) or changed
            if not self._alive:
                break
        return self._observe(changed)

    def click(self, x, y):
        if CLICK_ACTION not in self._by_value:
            raise ValueError("this game has no click action")
        self._alive = True
        cx, cy = max(0, min(63, int(x))), max(0, min(63, int(y)))
        self._keep_level_board()
        # Record what colour sat under the click before it happened. A placement is a
        # pick-up followed by a drop, so this log is what lets the harness reconstruct
        # the (colour, pad) order the agent actually used, without constraining how the
        # agent writes its code.
        self.click_log.append((cx, cy, int(self.grid()[cy][cx])))
        changed = self._step(CLICK_ACTION, {"x": cx, "y": cy})
        return self._observe(changed)

    def _keep_level_board(self):
        """Keep the fullest-tray board seen this level: the puzzle before it was touched."""
        parsed = frame_parse(self.grid())
        if not parsed:
            return
        n = len(parsed.get("tray") or [])
        if n > self._level_tray:
            self._level_tray = n
            self.level_grid = self.grid().copy()

    def forget_level_board(self):
        self.level_grid = None
        self._level_tray = -1

    def turn_budget(self) -> int:
        """Actions still available this turn. Stated so a turn can be planned, not guessed.

        Measured: a run stuck on one level tested eight assignments across twelve turns
        and ended with 250 of 8000 actions unspent, because the prompt showed only the run
        budget and the agent sized each turn to a single attempt.
        """
        return max(0, self._turn_action_cap - self._turn_spent)

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
        # The click log deliberately SURVIVES a reset. It used to be cleared here, to stop
        # a failed pre-reset attempt being banked as the one that won -- but the log is
        # now split into rounds and the winner is the last complete one, so clearing was
        # both unnecessary and harmful: it threw away the failed attempts, and those are
        # the only evidence that can separate two rules the solved levels both accept.
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


def prune(history: list[dict], keep_images: int = 2, budget: int = 320_000) -> list[dict]:
    """Recent turns in full, images only on the newest, older turns dropped.

    A 64x64 board as a data URL is expensive and a board from twelve turns ago is not the
    board. The *text* of recent turns is kept, because that is where the agent's reasoning
    and results live, and dropping all of it is what made the agent amnesiac.

    But keeping every turn's text forever is what killed a measured 6/8 run at turn 18 of
    80, with 7,700 of its 8,000 actions unspent: the trajectory grew past the context
    window, every later model call failed, and the loop span out the rest of its turns in
    silence. Unbounded memory is not memory, it is a fuse.

    So the trajectory is capped by size and filled from the most recent turn backwards.
    What falls off the end is not lost the way it used to be: the agent's notes, the rule
    gate's solved levels, and the refuted-attempt ledger are all re-sent in full every
    turn, and those are the parts that were worth carrying.
    """
    seen = 0
    out: list[dict] = []
    used = 0
    for message in reversed(history):
        content = message["content"]
        if isinstance(content, list):
            has_image = any(part.get("type") == "image_url" for part in content)
            if has_image:
                seen += 1
                if seen > keep_images:
                    content = [p for p in content if p.get("type") != "image_url"]
            message = {"role": message["role"], "content": content}
            size = sum(len(p.get("text", "")) or len(p.get("image_url", {}).get("url", ""))
                       for p in content)
        else:
            size = len(content or "")
        if out and used + size > budget:
            break
        used += size
        out.append(message)

    trimmed = list(reversed(out))
    # A conversation that starts on an assistant turn reads as though the agent spoke
    # first about a board nobody showed it.
    while trimmed and trimmed[0]["role"] == "assistant":
        trimmed.pop(0)
    return trimmed


def _parsed(grid):
    """Parse a stored grid and keep the grid with it, or None if it does not parse.

    The grid travels with the parse because a candidate rule must be able to derive its
    answer from the board itself. Handing it only pre-digested fields would let a "rule"
    read the harness's opinion instead of the picture, and the gate would be measuring
    frames.py rather than the agent.
    """
    if grid is None:
        return None
    parsed = frame_parse(grid)
    return {**parsed, "grid": grid.copy()} if parsed else None


def play(arc, game, client, deployment, max_turns, patience, action_cap,
         trace_path: str = "", seed: int = 0) -> dict:
    raw = arc.make(game, include_frame_data=True)
    # 4000 per turn let a single search loop swallow the whole run: one measured turn
    # spent 2075 actions and died 25 times inside it. RHAE squares the action count, so
    # a turn that large is unrecoverable no matter what the rest of the run does. 120 is
    # far above any honest solve here (level 1 needs 9, level 2 needs 15) and far below
    # the point where a loop stops being a mistake and becomes the whole run.
    env = Env(raw, raw.reset(), turn_action_cap=120)

    # Mechanics already learned on a previous run, replayed for zero actions. RHAE charges
    # every input that alters the game, so re-measuring facts we already hold is pure loss:
    # on sb26 a 141-action probe drops a perfect level-1 solve from 3.19% to 0.06%.
    mechanics = SkillLibrary().mechanics_for(game)

    # Phoenix, inside the loop rather than scoring from outside. The agent calls sense()
    # and accept() on its own beliefs while it plays, so a theory it has never tried to
    # break is reported back to it as unproven instead of being quietly trusted.
    phoenix = PhoenixLoop(scope=("level", env.best))

    # The agent's deliverable is a RULE, and this is what makes that true. Every level it
    # clears is kept with the board and the order that worked, and a proposed rule is
    # replayed over all of them for zero actions. Measured: the agent cleared level 2 by
    # writing `assignment = [(12, (22, 22)), (15, (28, 22)), ...]`, a lookup table, and
    # was rewarded because clearing the board was the only test. Cost per level then went
    # 9 -> 16 -> 38 -> 126 and level 5 never fell, because tables do not compound.
    rules = RuleGate()

    def propose(rule):
        return rules.propose(rule)

    def refuted(order):
        """Has this exact placement order already been played here and failed? FREE."""
        return rules.already_refuted(order)

    # Persistent namespace: this is the REPL the model keeps across turns.
    ns = {
        "press": env.press, "click": env.click, "look": env.look, "grid": env.grid,
        "alive": env.alive, "levels": env.levels, "reset": env.reset,
        "find": env.find, "note": env.note, "np": np,
        "objects": lambda: board_objects(env.grid()),
        "board": lambda: describe_board(env.grid()),
        "diff": diff_board,
        "layout": lambda: frame_parse(env.grid()),
        # `order()` used to be exposed here as frame_plan(env.grid()), which returned the
        # finished answer: [(9, (22, 29)), (14, (28, 29)), ...], every colour paired with
        # the exact coordinate to drop it on. frames.py derives that from hand-written
        # sb26 clue grammars (`_expand`, `_reference`), so handing it to the agent solves
        # the puzzle on the agent's behalf and measures the harness, not the agent.
        # `layout()` stays: it splits the board by shape alone and is perception, not an
        # answer. Discovery of the clue grammar has to be the agent's own work.
        "sense": phoenix.observe,
        "accept": phoenix.accept,
        "propose": propose,
        "refuted": refuted,
        "ACTIONS": list(env.actions),
    }

    tokens = 0
    stale = 0
    model_failures = 0
    idle = 0
    last_output = "(first turn; nothing run yet)"
    started = time.time()

    # The trajectory. Previously each turn sent only [SYSTEM, this turn], so the agent
    # re-derived the game's rules from scratch every turn and its entire memory was 25
    # note lines plus one stdout buffer. That is the amnesia Prime Agent's RLM exists to
    # remove: context is a variable the agent keeps, not something the harness discards.
    history: list[dict] = []

    for turn in range(max_turns):
        env.begin_turn()
        env.level_just_changed = False
        before_levels = env.best
        before_spent = env.spent
        notes = "\n".join(f"- {n}" for n in env.notes[-25:]) or "(none yet)"

        # The board changed, so what was true about the old board is no longer evidence.
        # Beliefs are scoped to the level and retired when it advances (issue #181).
        # Without this, level-1 facts stayed marked PROVEN on level 2 and the agent spent
        # a 2,075-action turn defending them against a board where they were false.
        retired = phoenix.enter(("level", env.best))
        if retired:
            env.note(
                f"level {env.best + 1}: retired {len(retired)} belief(s) earned on the "
                f"previous board; they must be re-earned here: {', '.join(retired)}"
            )
            notes = "\n".join(f"- {n}" for n in env.notes[-25:])

        # The exact board, recomputed every turn and never carried over. This is the fix
        # for the measured level-2 loss: the model kept applying level 1's hand-written
        # parser to level 2's layout, and the harness only ever told it in prose that its
        # coordinates might be stale. Prose cannot re-derive a layout; this can, and it
        # costs no actions. Turn 1 gets it too, which removes the guesswork that made the
        # first turn -- and therefore the whole run -- path dependent.
        board_text = describe_board(env.grid())
        learned = f"{mechanics}\n\n" if mechanics else ""

        content = [
            {
                "type": "text",
                "text": (
                    f"Game: {game}\n"
                    f"ACTIONS = {env.actions}"
                    f"{'  (6 is click(x,y))' if CLICK_ACTION in env.actions else ''}\n"
                    f"Levels: {env.best} of {env.frame().win_levels}\n"
                    f"Actions used: {env.spent} (soft budget {action_cap}); "
                    f"this turn you may spend {env.turn_budget()} more\n"
                    f"Deaths so far: {env.deaths}\n"
                    f"Colours on screen: {palette_legend(env.frame().frame)}\n\n"
                    f"{learned}"
                    f"{board_text}\n\n"
                    f"{phoenix.summary()}\n\n"
                    f"{rules.summary()}\n\n"
                    f"YOUR NOTES:\n{notes}\n\n"
                    f"OUTPUT FROM YOUR LAST CODE:\n{last_output}\n\n"
                    "Write this turn's code."
                ),
            },
            {"type": "text", "text": "Board now:"},
            {"type": "image_url", "image_url": {"url": data_url(env.frame().frame)}},
        ]

        history.append({"role": "user", "content": content})

        reply = None
        call_error = None
        starved = False
        for attempt in range(10):
            try:
                reply = client.chat.completions.create(
                    model=deployment,
                    messages=[{"role": "system", "content": SYSTEM}, *prune(history)],
                    max_completion_tokens=16000,
                    # gpt-5.6-sol rejects temperature and top_p (HTTP 400: only the default
                    # is supported) but honours seed and returns byte-identical output for
                    # it. The Arcade already defaults to seed=0, so fixing this one makes a
                    # whole run reproducible, which is what turns "it scored 3.1%" into a
                    # measurement rather than an anecdote.
                    seed=seed + turn,
                )
                break
            except Exception as exc:
                # A 429 is the endpoint asking us to slow down, not a verdict on the run.
                # Measured: a 6/8 run recorded 60 turns of silence and was read as the
                # agent running out of ideas, when it had run out of quota with 7,700 of
                # its 8,000 actions unspent. Waiting costs wall-clock; not waiting costs
                # the run.
                text = str(exc)
                if not ("429" in text or "rate limit" in text.lower()):
                    call_error = exc
                    break
                if attempt == 9:
                    starved = True
                    break
                nap = min(120, 10 * 2 ** attempt)
                print(f"  {game} t{turn + 1}: rate limited, waiting {nap}s "
                      f"(attempt {attempt + 1}/10)", flush=True)
                time.sleep(nap)

        if starved:
            # Running out of quota is not the same as running out of ideas, and it must
            # not be recorded as though it were. An earlier version re-raised here, which
            # killed the process and threw away a finished 6/8 run on its way out.
            print(f"  {game}: still rate limited after 10 tries; ending the run and "
                  f"keeping {env.best}/{env.frame().win_levels}", flush=True)
            history.pop()
            break

        try:
            if call_error is not None:
                raise call_error
            tokens += reply.usage.total_tokens
            answer = reply.choices[0].message.content or ""
            history.append({"role": "assistant", "content": answer})
            code = extract_code(answer)
            model_failures = 0
        except Exception as exc:
            # Loudly, and not forever. A silent `continue` here span a measured 6/8 run
            # through sixty remaining turns without a word once its trajectory outgrew
            # the context window, and the run was recorded as though it had simply
            # stopped improving. A failing model call is a fact about the harness and
            # has to look like one.
            model_failures += 1
            last_output = f"model call failed: {type(exc).__name__}"
            print(f"  {game} t{turn + 1}: MODEL CALL FAILED ({type(exc).__name__}: "
                  f"{str(exc)[:160]}) [{model_failures} in a row]", flush=True)
            history.pop()
            if model_failures >= 3:
                print(f"  {game}: three model calls failed in a row; stopping the run "
                      f"rather than burning {max_turns - turn - 1} turns in silence",
                      flush=True)
                break
            continue

        if not code:
            last_output = "no python block came back; reply with ```python ... ``` only"
            continue

        buffer = io.StringIO()
        cleared = ""
        try:
            with contextlib.redirect_stdout(buffer):
                exec(code, ns)  # noqa: S102 - executing model code is the design
            err = ""
        except LevelCleared as exc:
            # Plain feedback, not a traceback: the model needs to read this as a fact
            # about the game, not as a crash in its own code.
            err = ""
            cleared = str(exc)
            # Bank the board and the order that cleared it, so any rule proposed later
            # has to reproduce this level too. Placements are read back from the click
            # log, which keeps the agent free to write whatever code it likes rather
            # than forcing a placement API on it.
            level_board = _parsed(env.level_grid)
            if level_board is not None:
                order = placements_from_clicks(env.click_log, level_board)
                if order:
                    rules.remember(env.best, level_board, order)
            env.click_log = []
            env.forget_level_board()
            rules.clear_refuted()
        except StallDetected as exc:
            err = ""
            cleared = str(exc)
        except Exception:
            err = traceback.format_exc(limit=3)

        # A full set of placements that did not clear the level is the agent having
        # played an order and been refused by the board. That is exactly the evidence the
        # solved levels cannot supply, and it is captured without the agent having to
        # cooperate: the same click log, read the same way.
        if not cleared:
            played = _parsed(env.level_grid)
            if played is not None:
                for attempt in rounds_from_clicks(env.click_log, played):
                    rules.refute(attempt)

        out = buffer.getvalue()[-3000:]
        last_output = (out or "(no output printed)")
        if cleared:
            last_output += f"\n\n>>> {cleared}"
        if err:
            last_output += f"\nERROR:\n{err}"

        if env.level_just_changed:
            # Re-characterise mechanically instead of merely warning. The previous version
            # told the model its coordinates were "presumed INVALID" and hoped it would
            # re-derive a layout from a 64x64 image at ten pixels per cell. It could not,
            # and the measured result was seven consecutive turns of two actions each.
            # This hands it the new level's actual object list for zero actions.
            history.append(
                {
                    "role": "user",
                    "content": (
                        "LEVEL BOUNDARY. The game advanced to a new level in the middle "
                        "of your last code block, with no state change to signal it. "
                        "Every coordinate, colour mapping and helper function you derived "
                        "on the previous level is now WRONG. Do not reuse them, and do not "
                        "spend a turn deciding whether to trust them.\n\n"
                        "WARNING: the board below may be one frame STALE. Measured on this "
                        "game, the first read after a level change can still show the old "
                        "level. Spend one action, then call board() again and trust that "
                        "second reading over this one.\n\n"
                        "Here is the new level as it currently reads, at no action cost:\n\n"
                        f"{describe_board(env.grid())}\n\n"
                        "Count the pieces and the destinations from the FRESH list before "
                        "you click anything, then play the level."
                    ),
                }
            )

        gained = env.best - before_levels
        stale = 0 if gained > 0 else stale + 1

        # A zero-action turn gathers no evidence, so the next turn meets the same wall.
        # Measured on sb26: seven straight turns printing "verification mismatch; no
        # action" on level 2. Pushing the agent to "act instead of freezing", however,
        # measured far worse (RHAE 3.11% -> 0.018%, 1,227 actions, 13 deaths): it traded
        # paralysis for thrashing. The counter is kept for diagnosis; the harness does
        # not lecture the agent, because that specific intervention was gate-rejected.
        spent_this_turn = env.spent - before_spent
        idle = idle + 1 if spent_this_turn == 0 else 0

        if trace_path:
            with open(trace_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "turn": turn + 1,
                    "levels": env.best,
                    "actions_this_turn": env.spent - before_spent,
                    "total_actions": env.spent,
                    "code": code,
                    "output": last_output[-1500:],
                    "notes": env.notes[-8:],
                }) + "\n")

        print(
            f"  {game} t{turn + 1}: acts={env.spent - before_spent} total={env.spent} "
            f"deaths={env.deaths} lv={env.best}/{env.frame().win_levels} tok={tokens}"
            f"{' ERR' if err else ''}",
            flush=True,
        )

        if env.game_won:
            break
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
        "level_actions": env.level_actions,
        "deaths": env.deaths,
        "tokens": tokens,
        "elapsed_s": round(time.time() - started, 1),
        "seed": seed,
        "phoenix_proven": phoenix.established(),
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
    ap.add_argument("--trace", default="")
    ap.add_argument("--seed", type=int, default=0)
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
                 args.action_cap, args.trace, args.seed)
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
