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
import ast
import contextlib
import ctypes
import io
import json
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.arc.boardread import describe as describe_board  # noqa: E402
from evals.arc.boardread import diff as diff_board  # noqa: E402
from evals.arc.boardread import objects as board_objects  # noqa: E402
from evals.arc.frames import budget as frame_budget  # noqa: E402
from evals.arc.frames import parse as frame_parse  # noqa: E402
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
#: Azure spells the output cap `max_completion_tokens`; OpenAI-compatible hosts such as
#: Fireworks reject that name and want `max_tokens`. Resolved once at import so a
#: provider swap is an environment variable, never an edit.
_TOKEN_LIMIT = (
    {"max_tokens": 16000}
    if os.environ.get("ARC_PROVIDER", "azure").lower() in ("fireworks", "openai", "compat")
    else {"max_completion_tokens": 16000}
)
TERMINAL = ("GameState.WIN", "GameState.GAME_OVER")
# Measured, not assumed: with a level arranged correctly, press(7) does not clear it and
# a stray click does not clear it, but press(5) clears it immediately.
SUBMIT_ACTION = 5

SYSTEM = """You are playing an unfamiliar video game by WRITING PYTHON.

You see the board as an image. Nobody tells you the rules. Work them out by running code
and reading what comes back.

HOW YOU ARE SCORED, exactly, because it is not what you would guess:

    level_score = min(1.15, (human_actions_for_that_level / your_actions) ** 2)
    game_score  = sum(level_number * level_score) / sum(level_number for ALL levels)

Three things follow, and they decide how to play:

* EFFICIENCY IS SQUARED. Taking twice a human's actions scores 25%, not 50%. Ten times
  scores 1%. Clearing a level slowly is worth almost nothing -- one measured run cleared
  every level of a game and scored 13% because it spent four times the human's actions.
* FINISHING STILL MATTERS MOST. A level you never clear scores zero and its weight stays
  in the denominator, and later levels are weighted more heavily than early ones. So the
  target is to clear every level AND to do it in about the number of actions a human took.
* LOOKING IS FREE. Reading the board, listing objects, re-reading your notes and thinking
  cost NOTHING. Only acting is charged. So think as long as you like, and buy information
  with your eyes rather than with experiments: a burst of probing is the most expensive
  mistake available to you, and it is the measured cause of the worst runs on record.

Your code runs in a persistent namespace: variables and functions you define survive to
the next turn. Build up a toolkit as you learn the game.

API available to your code:

    press(n, times=1)   -> run action n, n times. Returns the observation dict.
    click(x, y)         -> click a cell (only if 6 is in ACTIONS).
    look()              -> observation dict WITHOUT acting.
    grid()              -> current board as a 64x64 numpy int array.
    alive()             -> False if the last action ended the game (you were reset).
    levels()            -> levels completed so far.
    reset()             -> put the CURRENT level back to pristine. Levels you have
                           already cleared STAY cleared; you do not go back to level 1.
                           COSTS NO ACTION: the scorecard counts a reset as a reset, not
                           as an action, so it never enters the number your score divides
                           by. It is the only free move in the game.
                           IT DOES NOT REFUND. Actions you already spent on this level
                           are still spent and still counted. Reset buys back the BOARD,
                           never the budget.
                           So use it exactly when undoing by hand would cost more actions
                           than replaying from pristine: a placement you cannot take back,
                           a piece pushed somewhere it cannot return from, an experiment
                           that left the board in a state you can no longer read. Paying
                           four actions to walk something back to where reset would have
                           put it for nothing is a straight loss.
    find(colour)        -> list of (y, x) cells of that colour.
    objects()           -> EXACT list of every discrete blob on the board right now:
                           [{colour, cx, cy, x0, x1, y0, y1, px}, ...]. Costs NOTHING.
    board()             -> the same thing as readable text, grouped into rows.
    layout()            -> the board split by SHAPE alone into {frames, pads, clues,
                           tray, well_formed, clue_structure}, or None if it is not drawn
                           that way.
                           FREE.
                           CHECK `well_formed` BEFORE YOU TRUST ANY OF IT. This split was
                           written for one shape -- a tray holding one piece per pad, plus
                           a clue row addressing them -- and `well_formed` is True only
                           when the board in front of you actually is that shape. Measured
                           across the 25 ARC-AGI-3 games: it holds on ONE of them. On the
                           others this returns pads and trays that are not pads and trays,
                           and planning against them is planning against a board that does
                           not exist. When it is False on a FRESH board, this abstraction
                           does not describe your game: use objects() and board(), which
                           describe any board, and work out this game's own structure from
                           what is drawn. (It also reads False on a half-played board of
                           the right shape, because the tray really has emptied. That is
                           not a warning, it is arithmetic.)
                           layout()["clue_structure"] describes the SHAPE OF THE CLUE ROW,
                           because the row is not always one ring per pad. It reports
                           {flat, colours, block, at, reduced, grid}: `flat` is False when
                           the row is longer than the pad count, `block` is the run of
                           colours that repeats, `at` where its occurrences start, and
                           `reduced` is the row with each occurrence replaced by a single
                           None.
                           Measured on level 5: nine rings over eight pads read as
                           colours=[6,14,8,8,14,8,8,11,15], block=[14,8,8],
                           reduced=[6,None,None,11,15].
                           `grid` reports how the clue is DRAWN: {rows, cols, drawn}.
                           The clue is not always one row. When rows > 1 and every column
                           holds one colour down all its rows, the extra rows RESTATE the
                           first and carry no colour of their own -- `colours` is then the
                           per-column reading, already collapsed, and `drawn` is the raw
                           ring list. Measured on level 8: twelve rings drawn 2x6 over
                           eight pads, drawn=[8,8,11,11,12,12,9,9,14,14,15,15] and
                           colours=[8,11,12,9,14,15]. Reading `drawn` as a rank of twelve,
                           or fusing its doubling with the tray's, is a dead end that has
                           cost a full level.
                           It tells you the row's SHAPE, not its meaning. Which pads the
                           reduced row addresses, which pads take the block, and what
                           colour belongs on a None are yours to work out -- and the tray
                           is the lever, because it holds exactly one piece per pad, so
                           whatever it has left over after the spelled-out colours are
                           accounted for is what the holes take.
    seated_variants()   -> {(x, y): (colour, hollow)} per pad. loose_variants() is the
                           same for tray slots. Both FREE.
                           TWO PIECES OF ONE COLOUR NEED NOT BE INTERCHANGEABLE: one can
                           be SOLID and one HOLLOW (a ring). Measured on level 8, whose
                           tray holds two 8s and two 9s -- of the four solid/hollow
                           choices on ONE AND THE SAME colour map, exactly one clears the
                           level. The same colour map was submitted and refused twice in
                           one run and cleared the level in another. So if a colour map
                           you have good reason to believe in is refused, check the
                           variants before abandoning it.
                           Say which one you want by writing (colour, "hollow") or
                           (colour, "solid") wherever a bare colour goes in an
                           assignment. A bare colour still means "any piece of it".
    note(text)          -> write to your notes, which you keep seeing. Returns its NUMBER.
                           This is the DEFAULT and it is where most of what you learn
                           belongs: where things sit, which cell is the exit, what this
                           board's layout is, what you just tried and what it did. Notes
                           are numbered so retract(n, because=...) can retire one, and
                           they are cleared at the level boundary because that is when
                           they stop being true. Measured: twelve runs called note() ZERO
                           times while calling mechanic() up to 111 times, and they are
                           the games that are stuck -- every board fact they learned went
                           into a list nothing can ever clear, so level 1's geometry was
                           still steering them on level 3.
    retract(n, because) -> RETIRE note n: you have disproved it. The claim moves to a
                           DISPROVED list you keep seeing, so you do not spend the rest of
                           the level re-deriving it. Use this the moment two of your notes
                           cannot both be true. Measured on another game: a run ended
                           holding both "do not click the active piece" and "click it to
                           drop it", acted on both, and re-derived the same two dead
                           theories four and six times. A memory that only grows
                           accumulates contradictions, not knowledge.
    mechanic(text)      -> record a RULE OF THE GAME. Notes die at the level boundary;
                           mechanics do not. The test is "would this still be true if the
                           board were redrawn?" -- "the exit is top-right" is a note,
                           "obstacles reflect particles" and "action 3 moves you north"
                           are mechanics. A COORDINATE IS NEVER A MECHANIC: "cross near
                           x=25" is a fact about one board, and written here it survives
                           every board after it and cannot be retracted by the level
                           change that disproved it. Measured on one game: level 1 fell
                           in 40 actions, its geometry was stored as rules of the game,
                           and the next level took 2,732 actions and never fell. Costs nothing, and it is the difference between
                           carrying the physics to level 2 and buying it again with
                           actions you are scored on. Measured: one run had 59 beliefs
                           retired at a level change, physics among them, and then spent
                           1,044 of its 1,055 actions on the level that followed.
                           Pass claim="..." to keep its sense() evidence too.
                           WRITE IT THE MOMENT YOU SEE IT, and write it BEFORE you spend
                           the next action. Two habits destroy these, and both were
                           measured across 249 attempted writes: 190 were placed under
                           `if levels() > start:`, and 217 were placed after a press or
                           click in the same turn. The first says a rule may only be
                           remembered on a turn that clears a level -- so on a game you
                           are losing it is never remembered at all, which is exactly the
                           game that needs it: one run attempted 84 writes, cleared no
                           level while making them, and stored none. The second loses the
                           write to a death, because a death raises immediately and the
                           rest of your code never runs -- so the lesson the death just
                           taught you is the one lesson never saved. A level clear is not
                           the evidence for "action 3 moves left"; the movement diff you
                           already printed is. Record from the observation, then act.
    unmechanic(n, because) -> drop a supposed rule. A mechanic is the one belief no level
                           change ever clears out from under you, so after a death or a
                           long stall these are the FIRST things to doubt.
    learn(name, source, description, tags=[]) -> SAVE WORKING CODE so the next level and
                           the next GAME can call it. mechanic() records a SENTENCE about
                           the game; learn() records the FUNCTION that acts on it, and a
                           function is the only thing that can be re-run without being
                           re-derived. Costs no actions. The source must define a function
                           called `name`; it is compiled before it is stored, so a syntax
                           error costs you the write and never the turn.
                           SAVE THE REUSABLE PART, NOT THE ANSWER. A skill tagged
                           general/primitive/perception is offered on OTHER games once it
                           has won; anything named solve_* is treated as this game's answer
                           and stays here. That split is not bureaucracy, it is measured:
                           the library currently holds seven skills, six of them per-game
                           solvers, and it has therefore transferred NOTHING across the
                           corpus. `solve_sb26()` cannot help you here. A function that
                           reads this board into pieces, finds which action moves what, or
                           locates the exit CAN, because those are facts about this
                           benchmark rather than about one board.
                           Write one the moment a piece of your code works twice. The
                           corpus is 25 games and every rule you do not save is a rule the
                           next game pays actions to discover again.
    sense(claim, ok)    -> record one trial of a belief. FREE.
    accept(claim)       -> {'ok': bool, 'reason': str}: is that belief actually proven?
    propose(rule)       -> test a rule against EVERY level you have already cleared. FREE.
                           Returns {'ok', 'tested', 'applies', 'passed', 'failed'}.
                           READ `tested` BEFORE YOU READ `ok`. When `tested` is 0 this
                           gate examined nothing, and it now says so instead of agreeing
                           with you: `applies` is False and `ok` is False, and that is
                           NOT a refutation of your rule. It happens on level 1, before
                           anything is solved, and permanently on any game whose boards
                           do not parse into pads and clues -- which is 24 of the 25.
    refuted(order)      -> has this exact placement order already failed here? FREE.

FIRST, FIND OUT WHICH KIND OF GAME YOU ARE IN, because the paragraph below is true of one
of the twenty-five and inert on the rest. Call layout() on the fresh board. If
`well_formed` is True you have a pads-and-clues game and the rule machinery below is your
main lever. If it is False, that machinery cannot describe your game at all: propose()
will never test anything, seated_variants()/loose_variants() describe furniture that is
not there, and objects(), board() and diff() are how you read what IS drawn. Do not spend
actions trying to make an inert gate turn green.

ON A PADS-AND-CLUES GAME, YOUR DELIVERABLE IS A RULE, NOT A SEQUENCE OF CLICKS. Write a
function rule(layout) that DERIVES the placements from the board it is given, and call
propose(rule). It is replayed against every level you have already solved, for zero
actions, and refused if it only fits the board in front of you.

This is the difference between winning and stalling, measured. A previous run cleared a
level by writing this:

    assignment = [(12, (22, 22)), (15, (28, 22)), (6, (40, 22)), ...]

That is a lookup table. It cleared that one board and was worth nothing on the next, so
cost per level went 9 -> 16 -> 38 -> 126 actions and the run died. A rule that reads the
board survives every level; a table has to be rebuilt each time, more expensively.

So when you find something that works, ask WHY it worked in terms of what is drawn on the
board. On a pads-and-clues game, write that as rule(layout) and propose() it: if it fails
an earlier level, that failure is the most useful thing you will see all run, because it
tells you exactly which part of your understanding is a coincidence. On every OTHER game
the lesson is the same and the instrument is different -- there is no rule gate to replay
against, so the thing you write the REASON into is mechanic(), which is the only memory
that survives the next board, and the only test available is whether it still holds when
that board arrives. What you write into note() is everything else, which is most of it:
where things are, what this board looks like, what you just tried. Either way the
deliverable is the reason, never the coordinates.

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


class Died(RuntimeError):
    """Raised the instant the move-bar runs out and the level restarts.

    Same reasoning as `LevelCleared`, and it was the missing half of it. A death silently
    resets the board mid-loop: pieces vanish, the tray refills, the bar goes back to full.
    Code that was walking a list of hypotheses carried on against a board it no longer
    understood, and the undo-then-rebuild step at the top of each iteration had nothing
    left to undo. Measured on level 7 of a fair run: seven deaths, every one of them
    partway through a batch of tests, and every test after the death wasted.

    Cutting the turn costs the untested tail of the batch -- which was worthless anyway --
    and buys the agent the one thing it never had: being told.
    """


def _death_forensics(prev_grid, term_grid, recent_actions) -> str:
    """What the world did in the instant the agent died.

    A death used to report a COUNT and a LIFE LENGTH. Neither says what killed you,
    and on `bp35-r3` that cost twenty-five deaths for three learned mechanics, all
    three of them movement primitives: the agent knew how to move and never learned
    what to avoid. It cannot be blamed for that. Nothing it could call would say.

    The evidence exists for exactly one statement. `_step` holds the outgoing frame
    while it computes `changed` and overwrites it on the next line, and the death
    handler then hands the terminal frame to `reset()`. So the two boards either
    side of the killing action are both in memory, and the difference between them
    IS the cause, expressed in the only vocabulary the game has: cells and colours.

    Deliberately game-agnostic. It does not know what a player is, or a hazard, or a
    road -- inventing those per game is how `parse` came to describe one game and
    answer for twenty-four. It reports what moved, from which colour to which, and
    where. On a crossing game that reads as "9 replaced 4 at x=5,y=2", which is the
    hazard naming itself.

    Never raises. A forensic sentence must not end a two-hour run, so every failure
    path returns a string -- an empty one if there is genuinely nothing to say.
    """
    try:
        import numpy as _np

        def _flat(g):
            if g is None:
                return None
            try:
                arr = _np.array(g)
            except Exception:
                return None  # ragged: modern numpy refuses outright
            if arr.dtype == object:
                return None  # ragged: older numpy builds an object array instead
            if not _np.issubdtype(arr.dtype, _np.number):
                return None  # a string, or anything else that is not a board
            if arr.ndim == 3:
                arr = arr[0]
            if arr.ndim != 2:
                return None
            return arr.astype(_np.int16)

        acts = [a for a in (recent_actions or []) if isinstance(a, int)]
        head = []
        if acts:
            head.append(f"  the action that killed you : {acts[-1]}")
            if len(acts) > 1:
                run_up = ", ".join(str(a) for a in acts[-9:-1])
                head.append(f"  the actions before it      : {run_up}")
        else:
            head.append("  the action that killed you : not recorded")

        a, b = _flat(prev_grid), _flat(term_grid)
        if a is None or b is None or a.shape != b.shape:
            body = ["  the board                  : could not be compared, so the cause "
                    "is not recorded here"]
        else:
            ys, xs = _np.where(a != b)
            n = int(len(xs))
            if n == 0:
                body = ["  the board                  : NO CELLS CHANGED on the action "
                        "that killed you, so whatever ended the life is not drawn on the "
                        "board. A budget running out looks exactly like this."]
            else:
                pairs = {}
                for y, x in zip(ys.tolist(), xs.tolist()):
                    pairs[(int(a[y][x]), int(b[y][x]))] = \
                        pairs.get((int(a[y][x]), int(b[y][x])), 0) + 1
                top = sorted(pairs.items(), key=lambda kv: -kv[1])[:6]
                shown = ", ".join(f"{f}->{t} x{c}" for (f, t), c in top)
                body = [
                    f"  cells that changed         : {n}",
                    f"  colour changes             : {shown}",
                    f"  where                      : x {int(xs.min())}..{int(xs.max())}, "
                    f"y {int(ys.min())}..{int(ys.max())}",
                ]
                # The single most likely cause: a colour that ARRIVED on top of another.
                arrivals = [((f, t), c) for (f, t), c in pairs.items() if f != 0 and t != 0]
                if arrivals:
                    (f, t), c = max(arrivals, key=lambda kv: kv[1])
                    body.append(
                        f"  colour {t} landed on colour {f} in {c} cell(s) -- if one of "
                        f"those is you, {t} is what to avoid")

        return ("\nWHAT CHANGED IN THE INSTANT YOU DIED (the terminal board, read before "
                "it was rebuilt):\n" + "\n".join(head + body) +
                "\nThis is the only record of the board that killed you. The next board "
                "is pristine, so a rule you do not write down now is gone.\n")
    except Exception:
        # A crash HERE would end a two-hour run over a sentence.
        return ""


class CodeTimeout(RuntimeError):
    """Raised when a turn's code block outruns its wall-clock budget.

    `exec` on model-written code had no time limit, and the failure that exposed it was
    not an infinite loop -- it was an honest search. On ka59 level 2 the model wrote a
    breadth-first search over the JOINT positions of four pieces on a 64x63 board, with
    no depth bound, no node cap and no time check. That frontier is around (64*63)**4
    states. The process ran 6.8 hours, burned 17,767 seconds of CPU and reached
    **42.5 GB of resident memory** before it was killed by hand.

    Two costs, and the second is the dangerous one. The game held a queue slot the whole
    time so the wave could not drain. And a 42 GB process on a box running eleven other
    agents is one OOM away from taking all of them with it -- a single bad cell becomes a
    corpus-wide outage.

    A wall-clock cap turns both into a normal, teachable turn: the agent is told its
    search was too big and gets to bound it, which is a thing models do well once asked.
    """


#: Ledger methods -- pure memory, no board access, safe to replay after an abort.
LEDGER_METHODS = frozenset({"mechanic", "unmechanic", "note", "retract"})


def _exec_bounded(code: str, ns: dict, seconds: float) -> None:
    """`exec(code, ns)` with a wall-clock cap. See `CodeTimeout` for what this cost us.

    The code runs in a daemon thread and its exception, whatever it is, is re-raised here
    so every existing handler -- LevelCleared, Died, StallDetected -- keeps working
    unchanged. `sys.stdout` is process-wide, so a `redirect_stdout` installed by the
    caller still captures the thread's prints.

    On timeout the worker is asked to stop via `PyThreadState_SetAsyncExc`, which raises
    between bytecodes. That reliably interrupts the pure-Python loops this exists for and
    cannot interrupt a blocking C call; the thread is a daemon so a stuck one can never
    hold the process open. The turn ends either way, which is the point -- the alternative
    was a game that never ends at all.
    """
    box: dict[str, BaseException | None] = {"exc": None}

    def run() -> None:
        try:
            exec(code, ns)  # noqa: S102 - executing model code is the design
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            box["exc"] = exc

    worker = threading.Thread(target=run, daemon=True, name="codeact-cell")
    worker.start()
    worker.join(seconds)

    if worker.is_alive():
        tid = worker.ident
        if tid is not None:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(tid), ctypes.py_object(CodeTimeout)
            )
        # A grace period so the async exception can land and unwind before the turn is
        # summarised. Not waited on indefinitely: a thread stuck inside a C call would
        # never come back and the run has to continue regardless.
        worker.join(5.0)
        raise CodeTimeout(
            f"your code was still running after {seconds:.0f}s and was stopped. "
            "Anything it had already done to the game still counts, and any mechanic() "
            "or note() it reached was kept.\n\n"
            "This is almost always an unbounded search. A breadth-first search over the "
            "JOINT positions of several pieces is astronomically large -- four pieces on "
            "this board is about (64*63)**4 states -- so it never finishes and spends the "
            "turn. Bound it: cap the nodes you will expand, cap the depth, or solve one "
            "piece at a time and keep the others fixed. A search that answers in seconds "
            "and might be wrong beats one that never answers."
        )

    if box["exc"] is not None:
        raise box["exc"]


#: Coordinates written into a permanent rule. `x=25`, `(31,16)`, `row 44`, `col 7`.
#: Deliberately not matched: a bare number, which is usually a step size ("moves you
#: 3 cells") and is a real mechanic.
_COORD = re.compile(
    r"\b[xy]\s*[=:]\s*-?\d+"
    r"|\(\s*-?\d+\s*,\s*-?\d+\s*\)"
    r"|\b(?:row|col|column)\s+-?\d+"
    r"|\bat\s+-?\d+\s*,\s*-?\d+",
    re.I,
)


def _looks_board_specific(text: str) -> str:
    """Mark a rule that named a coordinate, because that rule cannot be true twice.

    A mechanic is the one belief no level change ever clears. That is its value and
    it is also the whole risk: a fact about where something sits on THIS board,
    written as a rule of the game, is a lie that survives every board after it and
    cannot be retracted by the level boundary that disproved it.

    Measured on ka59: the run cleared level 1 in 40 actions, then recorded "enter the
    central vertical shaft near x=25, rise to y=26" and "align near y=44" as rules of
    the game, and spent 2,732 further actions on level 2 steering by level 1's
    geometry. Twelve runs across the corpus called mechanic() and note() zero times
    -- ar25, bp35, cn04, g50t, ka59, ls20, sp80 -- and they are, without exception,
    the games that are stuck.

    Marked rather than refused. "moves you 3 cells" is a real mechanic and a number is
    not evidence of anything by itself; the agent is the one that can tell a step size
    from a location, and it can only do that if it is shown which rules were flagged.
    """
    return "   <- names a coordinate; is this true on a REDRAWN board?" if _COORD.search(
        str(text)) else ""

#: Bumped when a defect changes what a recorded result MEANS, not merely how well the
#: agent plays. Version 2 is the level counter: the SDK's `levels_completed` can fall,
#: the harness gated the level transition on "greater than last frame", and so a card
#: written by version 1 can charge a level a fraction of the actions it truly cost.
HARNESS_VERSION = 2


def _salvage_ledger(code, ns, env):
    """Re-run the ledger writes the aborted cell never reached.

    `Died`, `LevelCleared` and `StallDetected` each abort the agent's cell part-way
    through, and every statement after the raise is skipped. Measured across 41 traces:
    96 calls to `mechanic`/`note`/`retract` sat after an action on a turn that died, and
    all 96 were lost. On `bp35-b` that was 17 of 17 -- the run recorded an EMPTY
    mechanics list while its own code had called `mechanic()` seventeen times. On a
    death-heavy game the lesson a death teaches is exactly the lesson a death destroys.

    Half of those calls build their text from local variables, so knowing the write
    before the cell runs is not possible. Re-running it afterwards is: the exec
    namespace survives the exception with every pre-action local still bound, so the
    statement means the same thing now as it would have meant then.

    Only statements whose calls are ALL ledger calls are replayed. That excludes
    anything touching the board -- after a death the board is pristine, so a re-read
    would answer about a different world -- and it is decided by the shape of the
    statement rather than by trusting a deny-list to stay complete. Lines that already
    wrote are skipped via `env._ledger_lines`, so a half-executed cell cannot
    double-record.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0

    saved = 0
    for stmt in tree.body:
        calls = [n for n in ast.walk(stmt) if isinstance(n, ast.Call)]
        if not calls:
            continue
        names = set()
        for call in calls:
            fn = call.func
            if isinstance(fn, ast.Attribute):
                names.add(fn.attr)
            elif isinstance(fn, ast.Name):
                names.add(fn.id)
            else:
                names.add("?")
        if not names <= LEDGER_METHODS:
            continue
        if {c.lineno for c in calls} & env._ledger_lines:
            continue
        try:
            exec(compile(ast.Module(body=[stmt], type_ignores=[]),  # noqa: S102
                         "<salvaged>", "exec"), ns)
            saved += 1
        except Exception:
            # A salvage that fails must cost nothing; the write was already lost.
            pass
    return saved


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
        self.level_notes: list[str] = []
        #: Rules of the game rather than facts about a board: these survive every level
        #: change. Per run only -- see `mechanic` for why this is never persisted.
        self.mechanics_learned: list[str] = []
        #: Set by the caller so `mechanic(claim=...)` can mark the belief durable too.
        self._keep = lambda claim: {"ok": False, "why": "no belief store attached"}
        # How many actions each life has lasted, and where the current one began.
        self.lives: list[int] = []
        self._life_mark = 0
        # The board as it stood before the CURRENT one, and the actions that got here.
        # Held so a death can be explained: `_step` replaces `self._frame` on the line
        # after it compares them, so without this the last-alive board is unreachable
        # by the time the death handler runs. See `_death_forensics`.
        self._prev_frame = None
        self._recent_actions: list[int] = []
        # Claims this board has DISPROVED. Kept apart from live notes so a dead theory
        # reads as dead rather than as one more thing that might be true.
        self.retracted: list[str] = []
        self._alive = True
        self._turn_action_cap = turn_action_cap
        self._turn_spent = 0
        # How many turns this level has resisted. Drives the per-turn cap: a level that
        # is not falling gets a narrower budget, so the next move has to be a better
        # idea rather than more attempts.
        self._turns_on_level = 0
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
        # Which lines of the CURRENT cell have already written to the ledger. A death
        # aborts the cell, and the salvage pass below re-runs the writes it never
        # reached; without this the writes that DID run would be replayed as duplicates.
        self._ledger_lines = set()
        # The colour a FULL move-bar is drawn in. A level always opens with the bar
        # untouched and therefore one colour, so it is learned there and handed back to
        # `budget` on every later read; without it a partly-eaten bar cannot say which of
        # its two segments is the remaining one, and guessing the direction would be the
        # same kind of invention this harness exists to remove.
        self._bar_colour = None
        self._bar_row = None
        # The bar's previous reading, as (row, {colour: cells}). The direction the bar
        # drains is not visible in one frame but is unambiguous across two, so the
        # harness watches rather than waiting to be told.
        self._bar_seen = None
        # The colour an EMPTY pad draws in, learned at level start when every piece is
        # still loose. A per-level property like the bar's length, so it is cleared on a
        # level change rather than carried over.
        self._empty_pad_colour = None
        self._pad_boxes = None
        self._tray_boxes = None
        self._piece_grow = 0

    def begin_turn(self) -> None:
        self._turn_spent = 0
        self.deaths_this_turn = 0
        # How long this level has resisted, which sets the per-turn action cap. Counted
        # here rather than in the turn loop so the Env owns its own budget: a limit whose
        # counter lives somewhere else is a limit that drifts from what it is limiting.
        self._turns_on_level += 1
        # alive() answers "did the last action kill me", not "have I ever died". It was
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
        if self._turn_spent >= self._live_turn_cap():
            raise TurnBudgetExhausted(
                f"this turn already spent {self._turn_spent} actions, and this level has "
                f"resisted {self._turns_on_level} turns, so the per-turn budget is "
                f"{self._live_turn_cap()}. That is deliberate: more attempts is the one "
                f"response this board has already refused. Read it again with board() and "
                f"objects(), decide which belief that reading contradicts, and spend the "
                f"next actions on a different IDEA. Looking costs nothing."
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
        before_best = self.best
        self.spent += 1
        self._turn_spent += 1
        changed = frame_key(nxt) != frame_key(self._frame)
        # The last board the agent was alive on, kept before the line below
        # overwrites it. It is the other half of the only comparison that can say
        # what killed you -- see `_death_forensics`.
        self._prev_frame = self._frame
        self._frame = nxt
        self.best = max(self.best, self._frame.levels_completed)
        # Recorded after the transition above: this is the action that produced the
        # frame now in hand, and on a death it is the action that ended the life.
        self._recent_actions.append(action_value)
        if len(self._recent_actions) > 24:
            del self._recent_actions[:-24]

        # The SDK's levels_completed is NOT monotone. On some games it falls back and
        # climbs again inside a single level, so "greater than last frame" fires on a
        # replay exactly as readily as on a first clear. Measured on s5i5-b: nine
        # transitions for two real levels, and the agent was told "LEVEL 1 CLEARED"
        # seven times while standing on level 3 -- each one wiping the level-scoped
        # notes and retractions it had just paid for, and each one restarting the
        # action mark so level 2 was charged the last 49 of the 375 actions it truly
        # cost. A new high-water mark is the only reading that means "a level I had
        # never finished before", which is precisely what RHAE credits, and it holds
        # len(level_actions) == levels_completed by construction.
        if self.best > before_best:
            actions = self.spent - self._level_mark
            self.level_actions.append(actions)
            self._level_mark = self.spent
            self.level_just_changed = True
            self._inert = 0
            # A new board earns a full budget again. The narrow cap is a response to THIS
            # level refusing, and carrying it into a level that has refused nothing would
            # punish the agent for the previous board's difficulty.
            self._turns_on_level = 0
            self.level_notes = []
            # Disproofs are scoped to the board that produced them, exactly like the
            # beliefs they killed. A theory refuted on level 1 may well be true on
            # level 2, and carrying the refutation across would forbid the right answer.
            self.retracted = []
            # A new level draws a fresh, full bar, and it may be a different length and a
            # different colour. Holding the old level's full-colour would make the first
            # read of the new bar answer with the wrong segment. The same applies to the
            # colour an empty pad draws in.
            self._bar_colour = None
            self._bar_row = None
            # The bar's previous reading, as (row, {colour: cells}), used to tell the
            # remaining segment from the spent one by watching which way it moves. Held
            # only within a life: every rebuild refills the bar, and a comparison across
            # a refill names the wrong half with full confidence.
            self._bar_seen = None
            self._empty_pad_colour = None
            self._pad_boxes = None
            self._tray_boxes = None
            self._piece_grow = 0
            raise LevelCleared(
                f"LEVEL {self.best} CLEARED in {actions} actions. "
                "The board below is a DIFFERENT level. Coordinates and helper functions "
                "from the previous level are presumed INVALID until you re-verify them."
            )

        if changed:
            self._inert = 0
            # WATCH THE BAR DRAIN, because one frame cannot say which way it drains.
            # A full-width two-segment row is bar-SHAPED, but which segment is the
            # remaining one is not visible in a single reading, so `frames.budget`
            # honestly refuses to guess and returns confirmed: False. It resolves
            # that by asking the caller for the colour seen when the bar was full --
            # and the caller is the agent, so on any game where the agent never
            # thinks to call clock() the bar is never identified at all. Measured on
            # bp35: eleven deaths, no clock() call in the entire run, and the death
            # notice therefore told it "this game DRAWS NO MOVE BAR" while row 63 was
            # visibly draining 63 -> 43 -> 38 -> 29 the whole time. That is the Gap 7
            # shape again: could-not-read reported as nothing-to-read.
            #
            # The harness does not need to be told. It sees every frame, so it can
            # watch instead of ask: over two frames the remaining segment SHRINKS and
            # the spent one grows, and that is a measurement rather than a guess.
            self._learn_bar_direction()
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
                # HOW LONG A LIFE LASTS, measured, because most games never draw it.
                # Eight of the 25 public games render no move bar at all, and on those the
                # agent has no way to see death coming: r11l died SEVENTEEN times in 690
                # actions and cleared one level, while ft09 -- which does draw a bar --
                # died four times in the same span. A game that will not show you your
                # budget can still be asked how long its lives have historically been.
                self.lives.append(self.spent - self._life_mark)
                self._life_mark = self.spent
                self._alive = False
                # WHAT KILLED YOU IS A PER-GAME FACT, so read it before the board that
                # holds the evidence is thrown away. The bar was the answer on sb26 and
                # the harness then told EVERY game the bar had run out -- including the
                # eight that draw no bar at all, where it also advised calling clock(),
                # which on those games honestly returns nothing. That is the same failure
                # as `parse` describing one game and answering for twenty-four.
                had_bar = False
                try:
                    had_bar = bool((self.clock() or {}).get("confirmed"))
                except Exception:
                    # A crash HERE would end a two-hour run over a cosmetic sentence.
                    # The board being read is the terminal frame, which is the one shape
                    # frames.budget has never been exercised against.
                    had_bar = False
                lifespan = self.lives[-1]
                # READ THE BOARD THAT KILLED YOU, now, while it still exists. The
                # reset below rebuilds it and the evidence is gone for good. This is
                # the same reasoning that already reads the bar here, applied to the
                # question the bar cannot answer: not "how long did I have" but
                # "what ended it".
                forensics = _death_forensics(
                    self._prev_frame.frame if self._prev_frame is not None else None,
                    self._frame.frame,
                    self._recent_actions,
                )
                self._frame = self._env.reset()
                self._bar_colour = None
                self._bar_row = None
                # The bar just refilled. Carrying its pre-death reading forward would
                # show the remaining segment GROWING and name the spent colour as the
                # budget -- a confident reading of exactly the wrong half.
                self._bar_seen = None
                self._inert = 0
                # A new life starts on a new board. Carrying the dead life's frame or
                # its action run-up into the next death would explain the wrong death.
                self._prev_frame = None
                self._recent_actions = []
                # The board has just been rebuilt underneath whatever code is running.
                # Letting the loop continue is the same silent corruption `LevelCleared`
                # exists to prevent: every remaining hypothesis in the batch would be
                # played against a board the agent thinks is mid-experiment and is in fact
                # brand new, and the undo step guarding each iteration would find nothing
                # to undo. Measured on level 7 of a fair run: 7 deaths, 1,367 actions, and
                # not one of the tests that followed a death could have meant anything.
                raise Died(
                    f"YOU DIED and level {self._frame.levels_completed + 1} RESTARTED "
                    f"(death {self.deaths} of this run). That life lasted {lifespan} "
                    "actions. The board is now PRISTINE, so nothing your code was "
                    "mid-way through still holds: re-read it before you act again.\n"
                    "WHAT THIS COST YOU is the "
                    f"{lifespan} actions, not the restart. A restart is free -- the "
                    "scorecard counts it as a reset, never as an action -- but every "
                    "action you spent getting here is still spent and still squared "
                    "against this level's score. So the loss is the work, and the "
                    "question to answer before spending more is which belief predicted "
                    "that this would work.\n"
                    + ("This game DRAWS A MOVE BAR: clock() reads it, costs no action, "
                       "and tells you how much of the budget this life affords. It is "
                       "not a clock -- on the game it was measured on it lost one cell "
                       "per piece DROPPED and one per SUBMIT, and nothing else. Confirm "
                       "on THIS game what moves it before you plan around it.\n"
                       if had_bar else
                       "This game DRAWS NO MOVE BAR, so clock() cannot warn you and "
                       "nothing will. The only budget estimate you have is the length "
                       "of the lives you have already lost, which is reported to you "
                       "each turn. Bank progress before you reach it.\n")
                    + forensics
                    + ("THE REST OF THAT TURN'S CODE NEVER RAN. This raise happened at "
                       "the action that killed you, so every line after it was "
                       "discarded -- including any note() or mechanic() you had written "
                       "at the bottom to record what the experiment showed. Measured "
                       "across 249 attempted mechanic writes, 217 sat after an action "
                       "and were lost this way whenever the turn died. Put the write "
                       "ABOVE the actions it is based on, so a death costs you the "
                       "actions and not the lesson as well.\n"
                       if self.mechanics_learned == [] and self.deaths >= 2 else "")
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

        THE CAP TIGHTENS WHILE A LEVEL REFUSES TO FALL, because a wide budget is only
        wide enough to brute-force with. At 120 a turn can test six or seven whole
        candidate solutions, and an agent that CAN search will search: measured on sb26,
        one model reached turn 11 holding a TRIED set of thirteen permutations and
        queued six more in a single turn, on a board with 7! = 5,040 of them. The model
        that cleared that same level did it in 26 actions by reasoning about the clue
        order instead.

        The number is not a guess. Runs that clear 6-8 levels spend 7-10 actions per
        turn; runs stuck below 5 spend 3-7 paid calls per turn but keep paying them for
        ninety turns. 120 was twelve times what a winning turn has ever needed, so it
        constrained nobody and licensed the one behaviour RHAE punishes quadratically.

        So the budget is generous while progress is happening and narrow once it stops.
        That is the opposite of what a searcher wants and exactly what a reasoner needs:
        when the board keeps refusing you, the next thing to change is the IDEA, and
        ideas are free -- board(), objects() and propose() cost no actions at all.
        """
        return max(0, self._live_turn_cap() - self._turn_spent)

    def _live_turn_cap(self) -> int:
        """The per-turn action cap, tightened by how long this level has resisted.

        Kept as a method rather than folded into `turn_budget` so `_step` and the
        prompt read the same number from one place; two callers computing a budget
        separately is how a limit becomes advisory.
        """
        stalled = self._turns_on_level
        if stalled >= 12:
            return min(self._turn_action_cap, 12)
        if stalled >= 6:
            return min(self._turn_action_cap, 25)
        return self._turn_action_cap

    def look(self):
        return self._observe()

    def _learn_bar_direction(self):
        """Identify the remaining segment of the move bar by watching it shrink.

        `frames.budget` can find a bar-SHAPED row on its own -- full width, one or
        two colours, at most two runs -- but it cannot tell from a single frame
        which of the two segments is the budget that is left and which is the part
        already spent. It refuses to guess, and asks the caller to hand back the
        colour the row showed while the bar was still full.

        That put the whole mechanism behind the agent's own curiosity. On sb26 and
        cd82 the agent called `clock()` early and the bar was identified; on bp35 it
        never called `clock()` once in thirty turns, so nothing was ever handed back,
        nothing was ever identified, and every death notice told it the game DRAWS NO
        MOVE BAR -- while row 63 drained 63 -> 43 -> 38 -> 29 in its own printed
        output. The harness turned "I could not read it" into "there is nothing to
        read", which is the same failure as `parse` describing one game and answering
        confidently for twenty-four.

        Nothing had to be asked. The harness holds every frame, and across two of
        them the ambiguity disappears: the remaining segment loses cells and the
        spent one gains exactly as many. So this watches every bar-shaped row and
        concludes on that conservation -- a bar keeps its width, so a cell leaving
        one segment arrives in the other, while a row that merely changes because
        an object crossed it does not balance.

        The previous reading is dropped wherever the board is rebuilt -- level
        change, death, manual reset -- because the bar REFILLS there. Comparing
        across a refill would show the remaining segment growing and name the spent
        colour as the budget, which is worse than not knowing: it is a confident
        reading of the wrong half.
        """
        if self._bar_colour is not None:
            return
        grid = self.grid()

        # A board that is still pristine answers outright: an untouched bar is a
        # single full-width run in a colour reserved for it, which is what the
        # strict pass in `frames.budget` already finds. bp35 opens exactly like
        # this, so this branch alone would have identified its bar on frame one --
        # nobody had ever looked.
        state = frame_budget(grid, None, self._bar_row)
        if state.get("confirmed") and state.get("full_colour") is not None:
            self._bar_colour = state["full_colour"]
            self._bar_row = state.get("row")
            return

        # Otherwise watch. Every full-width row of at most two colours and at most
        # two runs is a candidate; the real bar is the one that CONSERVES width as
        # it moves. Candidates are gathered here rather than through `budget`
        # because that function only offers a two-segment reading once it is told
        # which row to look at, and being told is the dependency this removes.
        h, w = grid.shape
        now: dict[int, dict[int, int]] = {}
        for y in range(h):
            cells = grid[y].tolist()
            seen = set(cells)
            if not 1 <= len(seen) <= 2:
                continue
            if 1 + sum(1 for a, b in zip(cells, cells[1:]) if a != b) > 2:
                continue
            now[y] = {c: cells.count(c) for c in seen}

        previous = self._bar_seen
        self._bar_seen = now
        if not previous:
            return

        found = []
        for y, after in now.items():
            before = previous.get(y)
            if not before or set(before) != set(after):
                continue
            shrank = [c for c, n in after.items() if n < before[c]]
            grew = [c for c, n in after.items() if n > before[c]]
            if len(shrank) != 1 or len(grew) != 1:
                continue
            # Conservation: what one segment lost, the other gained. A row redrawn
            # by something moving through it will not balance, and that is the
            # difference between a bar and ordinary board furniture that happens
            # to be two-toned.
            if before[shrank[0]] - after[shrank[0]] != after[grew[0]] - before[grew[0]]:
                continue
            found.append((y, shrank[0]))

        # Two rows draining at once means the board is doing something this rule
        # cannot read. Naming one of them would be a guess, and a guess reported as
        # a reading is the failure this whole file exists to remove.
        if len(found) == 1:
            self._bar_row, self._bar_colour = found[0]

    def clock(self):
        """The move-bar as the board draws it: cells left, used, total, fraction.

        Costs no action. Every earlier run believed this bar was a countdown clock,
        because that is what the harness told them it was; it is a MUTATION budget that
        only moves when a piece is DROPPED or a board is SUBMITTED. See `frames.budget`
        for the measurement. Reading it before planning a turn is what turns "how many
        hypotheses can I test" from a guess into arithmetic.
        """
        state = frame_budget(self.grid(), self._bar_colour, self._bar_row)
        if state.get("confirmed") and state.get("full_colour") is not None:
            self._bar_colour = state["full_colour"]
            # The bar's ROW is remembered as well as its colour. Measured on cd82: a static
            # strip of board furniture drawn in the same two colours as the bar was equally
            # "exclusive", won the tie on the lower row index, and made clock() report a
            # frozen 18/64 for the rest of the level. A frozen number is worse than none.
            self._bar_row = state.get("row")
        return state

    def grid(self):
        arr = np.array(self._frame.frame, dtype=np.int8)
        return arr[0] if arr.ndim == 3 else arr

    def seated(self):
        """Which colour currently sits on which pad, and None where a pad is empty.

        Costs no action. Two things here are cached at level start rather than re-derived,
        and both were measured going wrong:

        The PAD GEOMETRY. `parse` identifies pads as the smallest repeated blob on the
        board, which is true of a pristine level and false the moment pieces are placed:
        after one placement the occupied pad stopped being recognised as a pad at all and
        a tray slot was classified as one instead. Re-deriving the pad set from a
        half-built board therefore reports a different set of pads each time, which is
        useless to an executor trying to reach a target arrangement.

        The EMPTY-PAD COLOUR. An empty pad draws in its own colour, and which colour that
        is has to be learned, not assumed -- it is per level like the bar's length.

        A level opens with every piece still loose, so the first read where the tray is
        full establishes both, and both are forgotten when the level changes.
        """
        layout = frame_parse(self.grid())
        if not layout:
            return {}
        grid = self.grid()

        if self._pad_boxes is None and len(layout["tray"]) == len(layout["pads"]):
            self._pad_boxes = sorted(
                ({k: int(p[k]) for k in ("x0", "x1", "y0", "y1", "cx", "cy")}
                 for p in layout["pads"]),
                key=lambda p: (p["cy"], p["cx"]),
            )
            self._tray_boxes = sorted(
                ({k: int(t[k]) for k in ("x0", "x1", "y0", "y1", "cx", "cy")}
                 for t in layout["tray"]),
                key=lambda t: (t["cx"], t["cy"]),
            )
            # How far a piece overhangs the pad it sits on. Pieces are drawn larger than
            # pads, and a hollow one hides its hole exactly over the pad, so a pad has to
            # be read over the piece's footprint or an occupied pad looks empty.
            pad_w = self._pad_boxes[0]["x1"] - self._pad_boxes[0]["x0"] + 1
            piece_w = max(t["x1"] - t["x0"] + 1 for t in self._tray_boxes)
            self._piece_grow = max(0, (piece_w - pad_w) // 2)
        pads = self._pad_boxes
        if pads is None:
            return {}

        values, counts = np.unique(grid, return_counts=True)
        background = int(values[np.argmax(counts)])

        def dominant(pad):
            patch = grid[pad["y0"]:pad["y1"] + 1, pad["x0"]:pad["x1"] + 1]
            vals, cnts = np.unique(patch, return_counts=True)
            return int(vals[np.argmax(cnts)])

        # Learned from the pristine board, where every pad is empty, so the commonest
        # reading across the pads IS the empty colour. Done before any piece is read,
        # because reading a piece needs this value to know what to ignore.
        if self._empty_pad_colour is None and len(layout["tray"]) == len(pads):
            seen = [dominant(p) for p in pads]
            self._empty_pad_colour = max(set(seen), key=seen.count)

        def box_piece(pad):
            """The colour of the piece sitting here, or None if the pad is empty.

            Read over the PIECE's footprint, not the pad's. A pad is drawn 2x2 and a
            piece 4x4, and from level 4 some pieces are HOLLOW -- a ring with a 2x2 hole.
            Placed on a pad, such a piece puts its hole exactly over the pad box and its
            ring entirely outside it, so reading the pad's own pixels sees nothing but
            the hole. Measured on level 7: after placing a hollow c14, the pad box read
            `{4: 4}` -- four pixels of background, no trace of the piece. `seated()`
            called two occupied pads empty and the agent had to work around it by hand.

            Within that footprint the piece is whatever ink is neither the background nor
            the colour an empty pad draws in, which is the same reading `frames.parse`
            reaches by lifting each clue to its enclosing ring.
            """
            grow = self._piece_grow
            y0 = max(0, pad["y0"] - grow)
            y1 = min(grid.shape[0] - 1, pad["y1"] + grow)
            x0 = max(0, pad["x0"] - grow)
            x1 = min(grid.shape[1] - 1, pad["x1"] + grow)
            patch = grid[y0:y1 + 1, x0:x1 + 1]
            vals, cnts = np.unique(patch, return_counts=True)
            ink = [(int(c), int(v)) for v, c in zip(vals, cnts)
                   if int(v) not in (background, self._empty_pad_colour)]
            if not ink:
                return None
            count, colour = max(ink)
            # HOLLOW OR SOLID, and it matters. A ring covers fewer pixels of the same
            # footprint than a solid piece. Level 8's tray holds two 8s and two 9s where
            # one of each pair is hollow, and the pair is NOT interchangeable: measured,
            # of the four solid/hollow choices on one winning colour map, exactly one
            # clears the level. A reading that reports only colour therefore cannot tell
            # a winning board from a losing one.
            return (colour, count < int(patch.size))

        full = {(pad["cx"], pad["cy"]): box_piece(pad) for pad in pads}
        self._seated_full = full
        return {xy: (v[0] if v else None) for xy, v in full.items()}

    def seated_variants(self):
        """Which PIECE sits on which pad: {(x, y): (colour, hollow)} or None. Free.

        `seated` answers with colour alone, which is enough on every level whose tray
        holds one piece per colour and wrong on the ones that do not.
        """
        self.seated()
        return dict(getattr(self, "_seated_full", {}))

    def loose_variants(self):
        """The same reading for tray slots: {(x, y): (colour, hollow)}. Free."""
        self.loose()
        return dict(getattr(self, "_loose_full", {}))

    def _grab(self, xy):
        """A pixel certainly ON the piece at (x, y), for picking it up.

        A hollow piece's centre is its HOLE, and clicking a hole picks nothing up.
        Measured on level 7: two placements of hollow pieces silently did nothing and
        the board stayed two pads short while the executor reported it had moved them.
        The top-left corner of the piece's own footprint is on the drawn ring.
        """
        xy = (int(xy[0]), int(xy[1]))
        piece = {**getattr(self, "_loose_full", {}),
                 **getattr(self, "_seated_full", {})}.get(xy)
        if not piece or not piece[1]:
            return xy
        for box in (self._tray_boxes or []):
            if (int(box["cx"]), int(box["cy"])) == xy:
                return (int(box["x0"]), int(box["y0"]))
        for box in (self._pad_boxes or []):
            if (int(box["cx"]), int(box["cy"])) == xy:
                grow = self._piece_grow
                return (max(0, int(box["x0"]) - grow), max(0, int(box["y0"]) - grow))
        return xy

    def loose(self):
        """Tray slots that still hold a piece: {(x, y): colour}. Costs no action.

        Same reason `seated` caches its geometry. `parse` finds the tray by looking for
        the dominant repeated shape below the pad band, and once pieces start leaving it
        that shape stops repeating: measured, after a single placement the parse reported
        an EMPTY tray on a board that still held three pieces, which stalled the executor
        after one move.

        An emptied slot draws in the board's background colour -- measured directly, a
        slot went from 14 to 4 when its piece was placed, where 4 is the most common
        colour on the grid.

        A hollow piece is read the same way `seated` reads one: by its ink rather than by
        the commonest colour in its box, since the commonest colour inside a punched-out
        ring is the hole.
        """
        if self._tray_boxes is None:
            self.seated()  # learns the geometry when the board is still pristine
        if self._tray_boxes is None:
            return {}
        grid = self.grid()
        values, counts = np.unique(grid, return_counts=True)
        background = int(values[np.argmax(counts)])
        out = {}
        full = {}
        for slot in self._tray_boxes:
            patch = grid[slot["y0"]:slot["y1"] + 1, slot["x0"]:slot["x1"] + 1]
            vals, cnts = np.unique(patch, return_counts=True)
            ink = [(int(c), int(v)) for v, c in zip(vals, cnts) if int(v) != background]
            if ink:
                count, colour = max(ink)
                out[(slot["cx"], slot["cy"])] = colour
                full[(slot["cx"], slot["cy"])] = (colour, count < int(patch.size))
        self._loose_full = full
        return out

    def try_assignment(self, mapping, submit=True):
        """Put the board into `mapping` for the fewest bar cells, then submit.

        The agent supplies WHICH colour goes on WHICH pad -- that is the hypothesis and
        it stays entirely the agent's. This only executes it, and executes it at the
        price the game actually charges instead of the price a naive rebuild costs.

        Why it exists, measured. A hypothesis built from scratch costs one cell per drop
        plus one to submit: nine on an eight-pad level, so a 64-cell bar funds seven
        attempts per life. Level 7 has 8!/(2!3!3!) = 560 candidate assignments, and runs
        were spending 84 actions per hypothesis against a floor of 17 because each new
        candidate tore the whole board down and rebuilt it.

        Three measured mechanics make that unnecessary:

            lifting a piece already ON a pad ... 0 cells
            dropping onto an OCCUPIED pad ..... 1 cell, and it SWAPS the two pieces
            undo ............................. 0 cells

        Since every candidate is a permutation of the same tray, one assignment can be
        turned into another by swaps alone, and a swap fixes at least one pad for one
        cell. Two candidates differing on two pads cost 1 swap + 1 submit = 2 cells
        rather than 9. That is the difference between seven hypotheses per life and
        roughly twenty.

        Returns what it cost and what happened, so a turn can be planned against
        `clock()` rather than guessed.

        Accepts either shape the agent already writes: a list of (colour, (x, y)) pairs,
        which is what every rule in this harness returns, or a {(x, y): colour} dict.

        A colour may be QUALIFIED as `(colour, "hollow")` or `(colour, "solid")` when the
        tray holds more than one piece of it and they are drawn differently. Plain
        `colour` keeps its meaning -- any piece of that colour -- so nothing already
        written changes. The qualifier exists because on level 8 it is the whole answer:
        the colour map `8,11,12,9 / 9,14,15,8` was submitted and rejected twice in one
        run and cleared the level in another, and the difference was only which 8 and
        which 9 were used. Without a way to say it, the agent could neither state the
        answer nor learn anything from being refused.
        """
        target = {pad: _spec(colour) for colour, pad in _as_pairs(mapping)}

        before_bar = (self.clock() or {}).get("left")
        if not self.seated():
            return {"ok": False, "why": "board did not parse"}

        def satisfied(have, want):
            """Does the piece `have` = (colour, hollow) meet the spec `want`?"""
            if have is None:
                return False
            return have[0] == want[0] and (want[1] is None or have[1] == want[1])

        # Seat anything still loose first: a tray piece cannot be swapped with a pad.
        # Bounded by the pad count, not looped until stable, so a mechanic that does not
        # behave as measured cannot spin here.
        for _ in range(len(target) + 1):
            current = self.seated_variants()
            empties = [p for p in target if current.get(p) is None]
            if not empties:
                break
            spare = self.loose_variants()
            if not spare:
                break
            for pad in empties:
                want = target[pad]
                slot = next((s for s, piece in spare.items()
                             if satisfied(piece, want)), None)
                if slot is None:
                    # No loose piece meeting the spec; seat any piece here and let the
                    # swap pass below move it where it belongs.
                    slot = next(iter(spare))
                    pad = empties[0]
                self.click(*self._grab(slot))
                self.click(pad[0], pad[1])
                break

        # Every pad now holds something and the target is a permutation of what is
        # there, so one swap fixes at least one pad for one cell.
        for _ in range(len(target) + 1):
            current = self.seated_variants()
            wrong = [p for p in target if not satisfied(current.get(p), target[p])]
            if not wrong:
                break
            pad = wrong[0]
            donor = next((q for q in wrong
                          if q != pad and satisfied(current.get(q), target[pad])), None)
            if donor is None:
                break
            self.click(*self._grab(pad))      # lift a placed piece: free
            self.click(donor[0], donor[1])    # drop on an occupied pad: swap, 1 cell

        current = self.seated_variants()
        placed = all(satisfied(current.get(p), target[p]) for p in target)
        won = False
        if submit and placed:
            self.press(SUBMIT_ACTION)
            won = self.level_just_changed
        after = self.clock() or {}
        return {
            "ok": placed,
            "won": won,
            "cells_spent": (before_bar - after.get("left", before_bar)
                            if before_bar is not None else None),
            "cells_left": after.get("left"),
            "board": current,
        }

    def alive(self):
        return self._alive

    def levels(self):
        return self._frame.levels_completed

    def reset(self):
        self._frame = self._env.reset()
        self._alive = True
        # THE BOARD IS PRISTINE AGAIN, SO THE CACHED READINGS OF IT ARE NOT. The death
        # path already cleared these two; the manual path did not, and the difference
        # matters now that the prompt tells the agent reset is free and to use it. A
        # stale bar row survived a rebuild once already and reported a frozen 18/64 --
        # worse than reporting nothing, because a constant reads as a confident answer.
        self._bar_colour = None
        self._bar_row = None
        # And the bar refilled with the board, so its previous reading is now the
        # wrong side of a discontinuity, exactly as on the death path.
        self._bar_seen = None
        # A reset changes the board wholesale. Carrying the inert counter across it would
        # let a stall the reset just ended fire on the next action.
        self._inert = 0
        # The click log deliberately SURVIVES a reset. It used to be cleared here, to stop
        # a failed pre-reset attempt being banked as the one that won -- but the log is
        # now split into rounds and the winner is the last complete one, so clearing was
        # both unnecessary and harmful: it threw away the failed attempts, and those are
        # the only evidence that can separate two rules the solved levels both accept.
        return self._observe()

    def find(self, colour):
        ys, xs = np.where(self.grid() == int(colour))
        return list(zip(ys.tolist(), xs.tolist()))

    def _mark_ledger(self):
        """Remember that this line of the cell has already written to the ledger.

        Called from the ledger methods themselves rather than from the executor,
        because the write can happen inside a helper the agent defined this turn and
        the only honest record of "this one ran" is the frame that ran it.
        """
        try:
            self._ledger_lines.add(sys._getframe(2).f_lineno)
        except Exception:
            # Never let bookkeeping end a two-hour run.
            pass

    def mechanic(self, text, claim=None):
        """Record a rule of the GAME, which survives the level boundary.

        The level reset is correct about boards and wrong about physics. Measured on
        su15: at one level change the agent was told it had "retired 59 belief(s) earned
        on the previous board; they must be re-earned here" -- and among those 59 was
        "a black obstacle on a particle's predicted northwest cell reflects that
        particle". That is not a fact about level 1's layout. It is how the game works,
        it was true on every board, and re-earning it costs ACTIONS, which are the one
        thing RHAE squares. That run spent 1,044 of its 1,055 actions on a single level.

        So there are two memories now, and the split is the question "would this still be
        true if the board were redrawn?":

          note()     -- this obstacle sits at (14,7); the exit is top-right     (dies)
          mechanic() -- obstacles reflect particles; action 3 moves you north  (lives)

        Guessing wrong is cheap in one direction only, so the default stays `note`: a
        forgotten law costs a re-derivation, a wrong law kept forever costs the run.
        `unmechanic(n, because=...)` exists for exactly that, and a death or a stall
        should make you suspect these first, since they are the beliefs no level change
        has ever cleared out from under you.

        Pass `claim=` to also mark the matching Phoenix belief durable, so its EVIDENCE
        crosses the boundary with it rather than the bare sentence.

        This is per-run memory and is never written to `mechanics.json`. Learning inside
        a run is the agent playing; a file that grows between runs is the harness feeding
        the agent answers, which would make every later score dishonest.
        """
        entry = str(text)[:200]
        if entry in self.mechanics_learned:
            return {"ok": False, "why": "already recorded", "n": self.mechanics_learned.index(entry) + 1}
        self._mark_ledger()
        self.mechanics_learned.append(entry)
        out = {"ok": True, "n": len(self.mechanics_learned)}
        if _COORD.search(entry):
            out["warning"] = (
                "this names a coordinate, so it is probably a note() about THIS board "
                "rather than a rule of the game. A mechanic is never cleared by a level "
                "change, so a board fact written here is wrong on every board after it "
                "and cannot be retracted. If it would not survive a redraw, "
                f"unmechanic({len(self.mechanics_learned)}) and note() it instead."
            )
        if claim:
            out["belief"] = self._keep(str(claim))
        return out

    def unmechanic(self, number, because=""):
        """Drop a supposed rule of the game. See `mechanic` for why this must exist."""
        try:
            index = int(number) - 1
        except (TypeError, ValueError):
            return {"ok": False, "why": f"mechanic numbers are integers, got {number!r}"}
        if not 0 <= index < len(self.mechanics_learned):
            return {"ok": False,
                    "why": f"no mechanic {number}; {len(self.mechanics_learned)} recorded"}
        dead = self.mechanics_learned.pop(index)
        reason = str(because)[:160] or "no evidence given"
        self._mark_ledger()
        self.retracted.append(f"GAME RULE: {dead[:110]}  -- DISPROVED: {reason}")
        return {"ok": True, "retracted": dead, "because": reason,
                "remaining": len(self.mechanics_learned)}

    def note(self, text):
        """Record a fact worth carrying. Kept per level, not per run.

        The notes are the agent's own memory of WHY a theory died, and they are the only
        part of its reasoning that survives `prune` evicting the trajectory. They used to
        be capped at the last 25 across the whole run, which on a long level meant the
        agent's early conclusions were pushed out by its own later ones -- exactly when
        it most needed them, since by then the trajectory could no longer reach back
        either. Measured: a fair run worked level 7 for 45 turns with 22 turns of
        trajectory and a 25-note window.

        Scoped to the level, so clearing a level frees the budget rather than a note
        about level 7 evicting another note about level 7.

        Returns the note's NUMBER on this board, which is what `retract` takes.
        """
        self._mark_ledger()
        self.notes.append(str(text)[:200])
        self.level_notes.append(str(text)[:200])
        return len(self.level_notes)

    def retract(self, number, because=""):
        """Retire a belief this board has DISPROVED, and remember that it is dead.

        Notes were create-only, and a memory that can only grow accumulates
        contradictions rather than knowledge. Measured on cd82: the run ended still
        carrying both "Do not click active blocks: clicks merge their pixels into the
        fixed block" and "CLICK that domino to drop it" -- two notes that cannot both be
        true, both retained, both being acted on. Meanwhile the same dead theories were
        re-derived from scratch again and again: Voronoi on four separate turns,
        orientation on six.

        So this is the D in CRUD, and the retracted claim is KEPT, in a separate list, as
        a disproof. Knowing a theory is dead is worth as much as knowing one is true --
        it is what stops the twelfth rediscovery of the eleventh dead idea. `because` is
        the evidence that killed it and is not optional in spirit: a retraction with no
        reason is a mood, not a measurement.
        """
        try:
            index = int(number) - 1
        except (TypeError, ValueError):
            return {"ok": False, "why": f"note numbers are integers, got {number!r}"}
        if not 0 <= index < len(self.level_notes):
            return {"ok": False,
                    "why": f"no note {number}; this board has {len(self.level_notes)}"}
        dead = self.level_notes.pop(index)
        # `notes` carries the same text for the run-level tail; drop the last copy so the
        # two lists cannot disagree about what is currently believed.
        for i in range(len(self.notes) - 1, -1, -1):
            if self.notes[i] == dead:
                del self.notes[i]
                break
        reason = str(because)[:160] or "no evidence given"
        self._mark_ledger()
        self.retracted.append(f"{dead[:120]}  -- DISPROVED: {reason}")
        return {"ok": True, "retracted": dead, "because": reason,
                "remaining": len(self.level_notes)}

    def frame(self):
        return self._frame


def extract_code(text: str) -> str:
    if not text:
        return ""
    fence = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return fence.group(1).strip() if fence else ""


def make_client():
    """The endpoint decides the auth, because a key and a token are not interchangeable.

    Azure OpenAI authenticates with a bearer token from the local credential chain;
    Fireworks (and any other OpenAI-compatible host) authenticates with an API key and
    a plain base_url. Hardwiring the Azure path meant swapping models required editing
    the module, and an edit is a chance to break a running corpus.

    Set ARC_PROVIDER=fireworks with FIREWORKS_API_KEY, or leave it unset for Azure.
    """
    provider = os.environ.get("ARC_PROVIDER", "azure").lower()

    if provider in ("fireworks", "openai", "compat"):
        from openai import OpenAI

        key = (os.environ.get("FIREWORKS_API_KEY")
               or os.environ.get("OPENAI_API_KEY", ""))
        if not key:
            raise RuntimeError(
                f"ARC_PROVIDER={provider} needs FIREWORKS_API_KEY (or OPENAI_API_KEY) "
                "in the environment. Failing here rather than at turn 1 of a two-hour run."
            )
        base = os.environ.get(
            "ARC_BASE_URL",
            "https://api.fireworks.ai/inference/v1" if provider == "fireworks" else None,
        )
        return OpenAI(api_key=key, base_url=base) if base else OpenAI(api_key=key)

    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    # A TOKEN HANDED IN BEATS TWELVE PROCESSES FETCHING THEIR OWN. DefaultAzureCredential
    # shells out to the Azure CLI, and the CLI is a single-process tool: twelve agents
    # starting together produced ten runs stuck at turn 1 on ClientAuthenticationError,
    # each burning the retry ladder against contention rather than against a busy model.
    # Classifying that as congestion (Gap 17) stopped it ending runs, but a run that
    # retries forever at turn 1 is still a run that never plays.
    #
    # BUT IT MUST BE A PROVIDER, NOT A STRING. `azure_ad_token=<str>` is fixed for the life
    # of the client, so when it expires the run cannot recover: wave r2 lost twelve agents
    # mid-flight, every one looping AuthenticationError against a credential that would
    # never be valid again. `get_token` hands back the CLI's CACHED token too, so the
    # remaining life is unknown and can be minutes -- r2 died sixteen minutes in. The
    # launcher now writes a token FILE and refreshes it; this reads that file per request,
    # so one process fetches (no herd) and every agent still follows the refresh.
    token_file = os.environ.get("ARC_AAD_TOKEN_FILE", "").strip()
    if token_file:
        path = Path(token_file)

        def handed_token() -> str:
            """Current bearer token from the launcher's file.

            Called by the SDK on every request, so a refresh written by the launcher is
            picked up without restarting the run. Falls back to this process's own
            credential when the file is missing or stale -- that is the herd again, but a
            herd beats a dead run, and it only happens if the launcher stopped refreshing.
            """
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("expires_on", 0) - time.time() > 60:
                    return str(payload["token"])
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                pass
            return get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )()

        return AzureOpenAI(
            azure_endpoint=ENDPOINT,
            azure_ad_token_provider=handed_token,
            api_version="2024-12-01-preview",
        )

    token = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_endpoint=ENDPOINT,
        azure_ad_token_provider=token,
        api_version="2024-12-01-preview",
    )


def prune(history: list[dict], keep_images: int = 2, budget: int = 480_000) -> list[dict]:
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

    The cap is also what the run can AFFORD. Measured at a larger budget: 915,000 tokens
    bought seventeen turns before the endpoint started refusing calls, and the run ended
    on quota rather than on ideas, holding 6/8 with 7,700 of its 8,000 actions unspent.
    Context is not free context; every turn's history is re-sent on the next call.

    120,000 chars was that lesson over-applied. The model's window is a million tokens
    and the trajectory was capped at roughly thirty thousand, so a run lost its own
    reasoning after about twenty turns while runs were going 130-190 turns long -- the
    agent spent the back half of every long game re-deriving what it had already proved,
    and a re-derivation costs ACTIONS, which is the one thing RHAE squares. Measured
    across the corpus: 41,781 tokens per turn against a budget that could hold twelve
    times that.

    480,000 chars is ~120,000 tokens: four times the memory, still an eighth of the
    window, and still bounded so the fuse this docstring describes cannot be relit.

    What the budget is spent ON is a separate question from how big it is, and getting
    that wrong cost a level. The size of a message was its raw character count, so a
    kept image -- a base64 data URL, tens of thousands of characters of no use to a model
    that is being shown the current board anyway -- was charged against the same budget
    as the agent's reasoning and evicted several turns of it. Images are now excluded
    from the accounting entirely: the newest ones are still sent, but they no longer
    push text out. Measured on a fair run: 22 turns of history survived on a level the
    agent worked for 45, and it spent whole turns re-proposing assignments the ledger
    had already refuted.
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
            size = sum(len(p.get("text", "")) for p in content)
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


def _spec(colour):
    """Normalise a target colour into (colour, hollow) where hollow may be None = any.

    Accepts a bare colour, or a qualified `(colour, "hollow")` / `(colour, "solid")` /
    `(colour, True|False)`. A bare colour keeps meaning "any piece of this colour", so
    every rule already written behaves exactly as before.
    """
    if isinstance(colour, (tuple, list)) and len(colour) == 2:
        base, qual = colour
        if isinstance(qual, str):
            qual = qual.strip().lower()
            if qual in ("hollow", "ring", "open"):
                return (int(base), True)
            if qual in ("solid", "filled", "full"):
                return (int(base), False)
            raise ValueError(f"unknown piece qualifier {colour[1]!r}; "
                             "use 'hollow' or 'solid'")
        if isinstance(qual, bool):
            return (int(base), qual)
    return (int(colour), None)


def _as_pairs(assignment):
    """Normalise an assignment to [(colour, (x, y)), ...], whichever shape came in.

    The harness offers two shapes -- a list of (colour, (x, y)) pairs, which is what every
    rule in this repo returns, and a {(x, y): colour} dict, which is the natural way to
    write one by hand. `try_assignment` accepted both from the start; `refuted` accepted
    only the first and raised `TypeError: 'int' object is not subscriptable` on the other.
    Measured on a level-7 debug session, that cost a turn. Accepting one shape in one
    function and crashing on it in the next is the harness's bug, so both go through here.

    A colour may arrive QUALIFIED as `(colour, "hollow")` or `(colour, "solid")`. It is
    passed through unchanged rather than coerced with `int`, which would raise. That also
    makes the refutation ledger variant-aware: refusing one variant of a colour map must
    not mark the other three as tried, or the ledger rules out the answer. Measured on
    level 8, where exactly one of four variants of one colour map wins.
    """
    def colour(c):
        if isinstance(c, (tuple, list)) and len(c) == 2:
            return (int(c[0]), c[1])
        return int(c)

    if assignment is None:
        return []
    if isinstance(assignment, dict):
        return [(colour(c), (int(p[0]), int(p[1]))) for p, c in assignment.items()]
    return [(colour(c), (int(p[0]), int(p[1]))) for c, p in assignment]


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
         trace_path: str = "", seed: int = 0, start_level: int = 1,
         out_path: str = "", exec_timeout: float = 300.0) -> dict:
    raw = arc.make(game, include_frame_data=True)
    frame = raw.reset()

    # THE NUMBER THE AGENT IS SCORED AGAINST, handed to it rather than kept from it. ARC
    # publishes the per-level human baseline as `baseline_actions` in the same environment
    # metadata any agent can read, so this is the scoring function's own parameter, not a
    # hint about the puzzle: it says how MANY actions a level is worth, never which ones.
    # It is available for every environment including ones we have never seen, so an agent
    # built around it still works on the hidden set.
    #
    # Withholding it made the harness state a goal the agent could not aim at. The system
    # prompt used to say "you are scored on levels completed", which is simply false, and
    # the agent optimised exactly that: one measured run cleared all six levels of cd82 and
    # scored 13.67%, because it spent 1,026 actions where a human spent 171.
    baselines = {}
    try:
        for meta in arc.get_environments():
            if meta.game_id.split("-")[0] == game:
                baselines = {i + 1: n for i, n in enumerate(meta.baseline_actions or [])}
                break
    except Exception:  # noqa: BLE001 - a missing baseline must not stop a run
        baselines = {}

    # `start_level` is a DEBUG affordance and nothing else: it lets harness work on a late
    # level be iterated in seconds instead of paying the ~215 actions and dozen model calls
    # it costs to reach level 7 honestly. It cannot inflate a score -- `levels_completed`
    # stays at zero for every level that was skipped, which is the field every result
    # artifact in this repo reports -- and the result dict below is stamped so a jumped run
    # cannot be mistaken for a measurement later.
    jumped = start_level > 1
    if jumped:
        engine = getattr(raw, "_game", None)
        if engine is None or not hasattr(engine, "set_level"):
            raise RuntimeError("this engine exposes no set_level; start from level 1")
        engine.set_level(start_level - 1)
        # The board materialises on the next step, as it does after a real transition.
        # It must be a FREE one: action 5 is submit and costs a cell of the move bar, so
        # stepping with it opened the session on a partly-eaten bar whose full colour was
        # never learned, and clock() then read unconfirmed for the whole level.
        free = next((a for a in raw.action_space if int(a.value) == 7),
                    raw.action_space[-1])
        frame = raw.step(free) or frame
        print(f"  [debug session: started on level {start_level}; "
              f"levels_completed={frame.levels_completed} and stays uncredited]",
              flush=True)

    # 4000 per turn let a single search loop swallow the whole run: one measured turn
    # spent 2075 actions and died 25 times inside it. RHAE squares the action count, so
    # a turn that large is unrecoverable no matter what the rest of the run does. 120 is
    # far above any honest solve here (level 1 needs 9, level 2 needs 15) and far below
    # the point where a loop stops being a mistake and becomes the whole run.
    env = Env(raw, frame, turn_action_cap=120)

    # Mechanics already learned on a previous run, replayed for zero actions. RHAE charges
    # every input that alters the game, so re-measuring facts we already hold is pure loss:
    # on sb26 a 141-action probe drops a perfect level-1 solve from 3.19% to 0.06%.
    mechanics = SkillLibrary().mechanics_for(game)

    # THE SKILL LIBRARY, ACTUALLY CONNECTED. `skills.py` has implemented install /
    # describe / record / available since #177, and `codeact_agent` called exactly one
    # of them -- `mechanics_for`, a text blob scoped to this game. So no learned skill
    # ever reached the REPL, none was ever offered in the prompt, and no result was ever
    # booked. `skills.json` was the receipt: four of seven skills at 0W/0L, not because
    # they lost but because nothing counts. And `available()` only transfers a skill once
    # `wins > 0`, so with wins pinned at zero cross-game transfer could not fire even in
    # principle. The loop was open at both ends.
    #
    # This is the RSI claim the corpus mission rests on: learn on one game, generalise,
    # carry it to the next. It cannot compound while the library is write-only.
    library = SkillLibrary()

    # Phoenix, inside the loop rather than scoring from outside. The agent calls sense()
    # and accept() on its own beliefs while it plays, so a theory it has never tried to
    # break is reported back to it as unproven instead of being quietly trusted.
    phoenix = PhoenixLoop(scope=("level", env.best))
    # `mechanic(text, claim=...)` marks the matching belief durable, so the EVIDENCE for
    # a law crosses the level boundary with the sentence rather than only the sentence.
    env._keep = phoenix.keep

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
        """Has this assignment already been played here and failed? FREE.

        Accepts either shape the agent writes. `try_assignment` takes a list of
        (colour, (x, y)) pairs OR a {(x, y): colour} dict, and an agent that had just
        been handed that flexibility naturally passed the dict here too -- and got
        `TypeError: 'int' object is not subscriptable` from inside the harness. Measured
        on a level-7 debug session: it cost the agent a whole turn on the second turn of
        the level. An interface that accepts a shape in one function and crashes on it in
        the next is a harness defect, not a mistake by the caller.
        """
        return rules.already_refuted(_as_pairs(order))

    # Persistent namespace: this is the REPL the model keeps across turns.
    ns = {
        "press": env.press, "click": env.click, "look": env.look, "grid": env.grid,
        "alive": env.alive, "levels": env.levels, "reset": env.reset,
        "find": env.find, "note": env.note, "retract": env.retract, "np": np,
        "mechanic": env.mechanic, "unmechanic": env.unmechanic,
        "clock": env.clock,
        "seated": env.seated,
        "seated_variants": env.seated_variants,
        "loose_variants": env.loose_variants,
        "turn_budget": env.turn_budget,
        "try_assignment": env.try_assignment,
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
        "accept": phoenix.accept,        "propose": propose,
        "refuted": refuted,
        "ACTIONS": list(env.actions),
    }

    # WRITING A SKILL IS THE LEARNING HALF OF THE LOOP. `mechanic()` records a sentence;
    # this records CODE, which is the thing that can be re-run on the next level and the
    # next game. The name is deliberate: `learn` is what the prompt calls it, because
    # Gap 10 measured that a primitive whose description does not match its purpose is
    # simply never used.
    #
    # It refuses a skill that does not compile, so a syntax error costs the write rather
    # than the turn, and it refuses one that names a coordinate, for the same reason
    # Gap 18 exists -- a lookup table is not a rule and does not transfer.
    def learn(name, source, description, tags=None):
        source = str(source)
        try:
            compile(source, f"<skill {name}>", "exec")
        except SyntaxError as exc:
            return {"ok": False, "why": f"skill does not compile: {exc}"}
        if f"def {name}" not in source:
            return {"ok": False, "why": f"source must define a function called {name}"}
        library.add(name, game, source, str(description)[:300], tags)
        try:
            exec(source, ns)  # noqa: S102 - the agent's own code, same as a turn cell
        except Exception as exc:
            library.record(name, won=False)
            return {"ok": False, "why": f"skill saved but failed to install: {exc}"}
        return {"ok": True, "installed": name, "library": len(library.skills)}

    ns["learn"] = learn

    # Everything the library already knows, callable from turn 1. A skill that won on
    # another game is offered here too -- that is the generalisation step, and it is
    # gated on a recorded win rather than on optimism.
    installed_skills = library.install(ns, game)
    skills_text = library.describe(game)

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
    deaths_seen = 0
    best_seen = 0
    stuck_since = 0
    turn = -1
    # Overwritten by whichever exit actually fires; this is the one that means the loop
    # ran to the end of its turns with the game still winnable.
    stopped = "max_turns"

    for turn in range(max_turns):
        env.begin_turn()
        env.level_just_changed = False
        before_levels = env.best
        before_spent = env.spent
        # Patience counts turns since PROGRESS, and a new rule of the game is progress.
        # See the reset below for why level gain alone was the wrong measure.
        before_mechanics = len(env.mechanics_learned)

        def current_notes() -> str:
            """Everything learned on THIS level, plus a tail of what came before.

            The old window was the last 25 notes of the whole run, which on a long level
            meant the agent's early conclusions were evicted by its own later ones. That
            is the worst possible moment to lose them: by turn 30 of a level the
            trajectory no longer reaches back either, so a theory killed at turn 15 was
            gone from both places and got re-derived from scratch. Measured on level 7 of
            a fair run -- 45 turns of work against a 22-turn trajectory and a 25-note
            window. Notes are cheap; a level's worth costs a fraction of one turn.

            This board's notes are NUMBERED because they are addressable: `retract(n, ...)`
            retires one. And what has been disproved is listed separately, because a
            memory that only grows accumulates contradictions instead of knowledge --
            measured on cd82, which ended holding two notes that could not both be true
            while re-deriving the same dead theories four and six times over.
            """
            earlier = [n for n in env.notes[:-len(env.level_notes)]
                       if env.level_notes] or env.notes
            lines = []
            if env.mechanics_learned:
                lines.append(f"--- HOW THIS GAME WORKS ({len(env.mechanics_learned)}, "
                             f"survives every level; unmechanic(n, because=...) to drop "
                             f"one) ---")
                lines += [f"({i + 1}) {m}{_looks_board_specific(m)}"
                          for i, m in enumerate(env.mechanics_learned)]
                lines.append("--- facts about earlier boards ---")
            lines += [f"- {n}" for n in earlier[-8:]]
            if env.level_notes:
                lines.append(f"--- this level ({len(env.level_notes)} notes, "
                             f"retract(n) to retire one) ---")
                shown = env.level_notes[-60:]
                first = len(env.level_notes) - len(shown) + 1
                lines += [f"[{first + i}] {n}" for i, n in enumerate(shown)]
            if env.retracted:
                lines.append(f"--- DISPROVED on this board, do not re-derive "
                             f"({len(env.retracted)}) ---")
                lines += [f"x {r}" for r in env.retracted[-20:]]
            return "\n".join(lines) or "(none yet)"

        notes = current_notes()

        # The board changed, so what was true about the old board is no longer evidence.
        # Beliefs are scoped to the level and retired when it advances (issue #181).
        # Without this, level-1 facts stayed marked PROVEN on level 2 and the agent spent
        # a 2,075-action turn defending them against a board where they were false.
        #
        # THE OLD WORDING THEN MADE THE OPPOSITE MISTAKE. It said the retired beliefs
        # "must be re-earned here", which is true of a board fact and ruinous advice
        # about a law: measured on su15, one level boundary retired 59 beliefs including
        # "a black obstacle on a particle's predicted northwest cell reflects that
        # particle", and re-earning physics is paid for in the currency RHAE squares.
        # That run then spent 1,044 of 1,055 actions on the single level after it. So the
        # message now separates the two and says which one is free.
        retired = phoenix.enter(("level", env.best))
        if retired:
            env.note(
                f"level {env.best + 1}: retired {len(retired)} belief(s) that were only "
                f"tested on the previous board. Any of these that is a RULE OF THE GAME "
                f"rather than a fact about that board is still true here -- re-assert it "
                f"with mechanic(text) and it will never be retired again. That costs no "
                f"actions. Only the board-specific ones need re-earning: "
                f"{', '.join(retired)}"
            )
            notes = current_notes()

        # A DEATH IS THE STRONGEST REFUTATION THE GAME EVER HANDS OUT, and it used to
        # teach nothing. Measured on cd82: six deaths cost 463 of the run's 713 actions --
        # 65% of everything it spent -- and after each one the agent resumed the same
        # theory that had just walked it into the wall. Prime Agent's harness reviews a
        # trajectory and applies the smallest relevant edit to its own state; this is the
        # cheapest honest version of that, triggered by the one event that proves an edit
        # is owed. It costs no actions, and it asserts nothing about WHICH belief is wrong,
        # because that is the agent's job and not the harness's guess.
        died = env.deaths - deaths_seen
        deaths_seen = env.deaths
        if env.best > best_seen:
            best_seen = env.best
            stuck_since = turn
        stalled = turn - stuck_since

        consolidate = ""

        # What this level is WORTH, in the currency the benchmark actually pays in. The
        # agent cannot aim at an efficiency target it is never shown, and it was previously
        # shown only a soft action budget of its own harness's invention.
        spent_here = env.spent - sum(env.level_actions)
        par = baselines.get(env.best + 1)
        pace = ""
        if par:
            ratio = par / max(1, spent_here)
            worth = min(1.15, ratio ** 2)
            pace = (f"THIS LEVEL: a human took {par} actions; you have spent "
                    f"{spent_here}. Finishing now would score {worth:.0%} of it "
                    f"(cap 115%). Every further action lowers that, squared.\n")

        # A LIFE EXPECTANCY FOR GAMES THAT DRAW NO BAR. Eight of the 25 public games
        # render no move meter, and on those `clock()` honestly reports nothing -- which
        # leaves the agent with no way at all to see a death coming. Measured: r11l died
        # SEVENTEEN times in 690 actions and cleared one level; ft09, which does draw a
        # bar, died four times over a comparable run. The game will not show the budget,
        # but the agent's own history estimates it, and an estimate beats blindness.
        # Suppressed when the bar IS readable, so this never argues with a real reading.
        bar = env.clock() or {}
        if not bar.get("confirmed") and env.lives:
            typical = min(env.lives)
            since = env.spent - env._life_mark
            pace += (f"NO MOVE BAR IS DRAWN on this game, so nothing warns you before a "
                     f"death. Measured from your own {len(env.lives)} death(s): the "
                     f"shortest life so far lasted {typical} actions and you have spent "
                     f"{since} since the last one. Treat that as your budget and bank "
                     f"progress before you reach it.\n")

        # NOT GATED ON HAVING NOTES, WHICH IS THE WHOLE POINT. Both of these used to read
        # `and env.level_notes`, so an agent with an empty notebook was told nothing --
        # and an empty notebook is not a sign of an agent that needs no help, it is the
        # signature of the ones that are stuck. Measured: bp35 died 20 times across 45
        # turns holding zero notes and zero mechanics, and received neither message; ka59
        # cleared level 1 at turn 6 and spent 90 further turns, 2,732 actions and 99% of
        # its budget without one. Corpus-wide, 62% of every action ever spent came after
        # the run's last level clear. The guidance was gated on the agent having already
        # done the thing the guidance exists to ask for.
        if died:
            consolidate = (
                f"\nYOU DIED {died}x SINCE YOUR LAST TURN, and a death costs a whole bar.\n"
                + ("Something you currently believe predicted that would work. Before you "
                   "spend another action, find the note that is wrong and retract(n, "
                   "because=...) it. If you are unsure which, retract the one you were acting "
                   "on when you died: a wrong disproof is cheap and a repeated death is not.\n"
                   if env.level_notes else
                   "YOU ARE HOLDING NO NOTES, so there is nothing here to correct -- and "
                   "that is the problem, not a clean slate. You died believing something, "
                   "and because it was never written down you will believe it again next "
                   "turn and die the same way. Write what you expected and what happened "
                   "instead with note(text) -- it is FREE, it costs no action, and it is "
                   "the only thing that makes the next death a different death.\n")
                + ("Check the HOW THIS GAME WORKS list first. Those are the beliefs no "
                   "level change has ever cleared out from under you, so a rule that was "
                   "only ever true of one board can survive there indefinitely and steer "
                   "every plan you make. unmechanic(n, because=...) drops one.\n"
                   if env.mechanics_learned else "")
            )
        elif stalled >= 6:
            # BEING STUCK IS THE COMMON FAILURE, AND IT USED TO TRIGGER NOTHING. The
            # death-only prompt above fires on a rare event; grinding is the frequent one.
            # Measured on cd82: one run spent 66 consecutive turns and ~700 actions on a
            # single level, never cleared it, and called retract() ZERO times -- while
            # another run cleared that same level in 68 actions.
            #
            # THE WORDING MATTERS AND THE FIRST ONE COST A RUN. Telling a stuck agent to
            # "try something structurally different" was measured as an instruction to run
            # more experiments: actions went from 1,026 to 4,212, one level alone ate 2,731
            # of them, and the score fell from 13.67% to 0.53%. Under RHAE the action count
            # is squared, so encouraging exploration is close to the most expensive advice
            # available. What a stuck agent needs is a different IDEA, and ideas are free:
            # reading the board, listing objects and re-reading the goal cost nothing at
            # all. So the stall points at the free tools and at retraction, and explicitly
            # warns against buying information with actions.
            consolidate = (
                f"\nYOU HAVE SPENT {stalled} TURNS ON THIS LEVEL WITHOUT CLEARING IT.\n"
                + ("That is evidence about your BELIEFS, not your effort: one of the notes "
                   "above is wrong, and while you keep it you are searching a space that does "
                   "not contain the answer.\n"
                   if env.level_notes else
                   "That is evidence about your BELIEFS, not your effort. YOU ARE HOLDING NO "
                   "NOTES, so every turn starts from the same place the last one did and "
                   "re-derives what it already learned -- which is why this level is not "
                   "moving. Measured across the corpus: 62% of every action ever spent came "
                   "after the run's last cleared level, and the runs that never wrote a note "
                   "are the ones that never cleared another. Write down what you believe "
                   "about this board with note(text) BEFORE your next action; it is free, "
                   "and you cannot retract a belief you never recorded.\n")
                + "Do this with FREE tools before you spend another action -- looking costs "
                "nothing and every action is squared against your score. Re-read the board "
                "with objects() and board() as if you had just arrived at it, decide which "
                "note that reading contradicts, and retract(n, because=...) it. Then act "
                "on the new idea, not on more experiments: more probing is what turned a "
                "1,026-action run into a 4,212-action one.\n"
                "Look at the PHOENIX block too. A claim there reads 'unproven' when you "
                "have only ever seen it CONFIRMED -- you have never tried to break it, so "
                "it is a guess you got attached to, and it is the most likely thing "
                "keeping you here. Design this turn to FALSIFY your load-bearing claim "
                "rather than to succeed with it.\n"
            )
            if stalled >= 14:
                consolidate += (
                    "You are well past the point where refining one belief helps. Retract "
                    "SEVERAL and re-derive this board from what is drawn -- still using "
                    "the free tools, still without a burst of experiments.\n"
                )

        # The exact board, recomputed every turn and never carried over. This is the fix
        # for the measured level-2 loss: the model kept applying level 1's hand-written
        # parser to level 2's layout, and the harness only ever told it in prose that its
        # coordinates might be stale. Prose cannot re-derive a layout; this can, and it
        # costs no actions. Turn 1 gets it too, which removes the guesswork that made the
        # first turn -- and therefore the whole run -- path dependent.
        board_text = describe_board(env.grid())
        learned = f"{mechanics}\n\n" if mechanics else ""
        # Offered every turn, not just the first. A skill the agent is told about once
        # on turn 1 and never again is a skill it has forgotten by turn 40 -- the same
        # amnesia the trajectory history exists to fix.
        skills_block = (
            f"SKILLS you can call right now (learned code, costs no actions to read):\n"
            f"{skills_text}\n"
            f"learn(name, source, description, tags=[]) saves a NEW one. Save the "
            f"REUSABLE part, not the whole solution: a function that reads this board "
            f"into pieces transfers to the next game, `solve_{game}()` does not.\n\n"
        ) if skills_text and skills_text != "(no skills learned yet)" else (
            f"SKILLS: none learned yet. learn(name, source, description, tags=[]) saves "
            f"a function so the next level and the next GAME can call it. Save the "
            f"reusable part -- a board reader transfers, a coordinate table does not.\n\n"
        )

        content = [
            {
                "type": "text",
                "text": (
                    f"Game: {game}\n"
                    f"ACTIONS = {env.actions}"
                    f"{'  (6 is click(x,y))' if CLICK_ACTION in env.actions else ''}\n"
                    f"Levels: {env.best} of {env.frame().win_levels}\n"
                    f"{pace}"
                    f"Actions used: {env.spent} (soft budget {action_cap}); "
                    f"this turn you may spend {env.turn_budget()} more"
                    f"{'  (NARROWED: this level has resisted ' + str(env._turns_on_level) + ' turns, so more attempts is not the move -- change the IDEA. Reading the board is free.)' if env.turn_budget() < env._turn_action_cap else ''}\n"
                    f"Deaths so far: {env.deaths}\n"
                    f"Colours on screen: {palette_legend(env.frame().frame)}\n"
                    f"{consolidate}\n"
                    f"{learned}"
                    f"{skills_block}"
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
        # Measured on tu93: six concurrent runs share one endpoint's tokens-per-minute,
        # so process count buys no throughput -- it splits the same quota and adds 429
        # churn. The old ten-attempt ladder gave up after ~12 minutes and ended tu93 at
        # 1/9 with 280 of its 8,000 actions unspent. Wall-clock is the cheapest thing we
        # spend; a run is worth ~4M tokens. Wait far longer before conceding.
        for attempt in range(40):
            try:
                reply = client.chat.completions.create(
                    model=deployment,
                    messages=[{"role": "system", "content": SYSTEM}, *prune(history)],
                    # gpt-5.6-sol rejects temperature and top_p (HTTP 400: only the default
                    # is supported) but honours seed and returns byte-identical output for
                    # it. The Arcade already defaults to seed=0, so fixing this one makes a
                    # whole run reproducible, which is what turns "it scored 3.1%" into a
                    # measurement rather than an anecdote.
                    seed=seed + turn,
                    # `max_completion_tokens` is the Azure spelling and OpenAI-compatible
                    # hosts reject it. Named once, here, so swapping providers is an
                    # environment variable rather than an edit to a file a corpus is
                    # mid-run against.
                    **_TOKEN_LIMIT,
                )
                break
            except Exception as exc:
                # A 429 is the endpoint asking us to slow down, not a verdict on the run.
                # Measured: a 6/8 run recorded 60 turns of silence and was read as the
                # agent running out of ideas, when it had run out of quota with 7,700 of
                # its 8,000 actions unspent. Waiting costs wall-clock; not waiting costs
                # the run.
                #
                # A TIMEOUT UNDER LOAD IS THE SAME SIGNAL WEARING A DIFFERENT NAME. This
                # test used to match only "429"/"rate limit", so an APITimeoutError fell
                # through to call_error, raised, and burned one of the three model-failure
                # strikes that end a run. Measured: a four-run batch ALL died that way --
                # lp85 at 7/8 with 90 turns and 2 deaths left in it, su15, sc25 and vc33
                # likewise -- every one of them filed as "max_turns" while sitting at
                # roughly a third of its turn budget. Congestion must go to the ladder.
                # A CREDENTIAL REFRESH UNDER LOAD IS THE SAME SIGNAL AGAIN. Three
                # concurrent runs refresh their tokens against one Azure CLI, contend,
                # and one of them gets `CredentialUnavailableError: Failed to invoke the
                # Azure CLI`. Nothing about the run is wrong and the next attempt
                # succeeds. Measured: ar25 was at 5/8 with level 5 cleared in 59 actions
                # -- still solving, and solving fast -- when three of these in a row
                # spent all three model-failure strikes and ended it. The scorecard filed
                # that as `model_failures`, which reads as the model breaking rather than
                # as a token that was busy for ninety seconds.
                # Classify on the type name as well as the message. `CredentialUnavailable`
                # is the durable half of that signal; the sentence after it is the Azure
                # CLI's wording and is not ours to depend on.
                text = f"{type(exc).__name__} {exc}".lower()
                congested = (
                    "429" in text
                    or "rate limit" in text
                    or "timeout" in text
                    or "timed out" in text
                    or "connection" in text
                    or "temporarily unavailable" in text
                    or "503" in text
                    or "500" in text
                    or "overloaded" in text
                    or "credentialunavailable" in text
                    or "failed to invoke the azure cli" in text
                    or "azure cli" in text
                    or "token" in text and "expired" in text
                )
                if not congested:
                    call_error = exc
                    break
                if attempt == 39:
                    starved = True
                    break
                nap = min(120, 10 * 2 ** attempt)
                print(f"  {game} t{turn + 1}: congested ({type(exc).__name__}), waiting "
                      f"{nap}s (attempt {attempt + 1}/40)", flush=True)
                time.sleep(nap)

        if starved:
            # Running out of quota is not the same as running out of ideas, and it must
            # not be recorded as though it were. An earlier version re-raised here, which
            # killed the process and threw away a finished 6/8 run on its way out. It
            # also left `stopped` at its initial "max_turns", so tu93 -- which died on a
            # 429 at turn 29 of 160 -- was filed as having exhausted its turn budget.
            stopped = "rate_limited"
            print(f"  {game}: still rate limited after {attempt + 1} tries; ending the "
                  f"run and keeping {env.best}/{env.frame().win_levels}", flush=True)
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
                stopped = "model_failures"
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
        advanced = False
        env._ledger_lines = set()
        try:
            with contextlib.redirect_stdout(buffer):
                _exec_bounded(code, ns, exec_timeout)
            err = ""
        except LevelCleared as exc:
            # Plain feedback, not a traceback: the model needs to read this as a fact
            # about the game, not as a crash in its own code.
            err = ""
            cleared = str(exc)
            advanced = True
            _salvage_ledger(code, ns, env)
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
        except CodeTimeout as exc:
            # Not a crash and not a game event: the cell was too expensive. Reported as
            # feedback so the agent bounds its next search, and the ledger writes it did
            # reach are salvaged exactly as on the death path.
            err = ""
            cleared = str(exc)
            _salvage_ledger(code, ns, env)
        except StallDetected as exc:
            err = ""
            cleared = str(exc)
            _salvage_ledger(code, ns, env)
        except Died as exc:
            # A death is feedback about the game, not a crash in the agent's code.
            err = ""
            cleared = str(exc)
            # The conclusions this cell was about to record are the ones a death is
            # worth. Recover them before the turn is summarised.
            rescued = _salvage_ledger(code, ns, env)
            if rescued:
                cleared += (f"\n({rescued} ledger write(s) your code had not reached when "
                            "you died were recorded anyway.)")
        except Exception:
            err = traceback.format_exc(limit=3)

        # A full set of placements that did not clear the level is the agent having
        # played an order and been refused by the board. That is exactly the evidence the
        # solved levels cannot supply, and it is captured without the agent having to
        # cooperate: the same click log, read the same way.
        #
        # Gated on ADVANCED, not on whether any message came back. Gating on the message
        # meant a turn that ended in a stall -- or, once deaths began interrupting the
        # turn, any turn that ended in a death -- threw away every attempt it had played.
        # Those are the turns whose attempts matter most: a death arrives precisely when
        # the agent has spent a whole life being refused, and forgetting the refusals let
        # the next turn replay them.
        if not advanced:
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

        # PATIENCE MEASURES PROGRESS, AND A LEVEL IS NOT THE ONLY KIND. This reset used to
        # fire only on `gained > 0`, which made patience mean "turns without COMPLETING a
        # level" -- so any game whose level 1 takes longer than the budget dies no matter
        # how well it is doing. Measured on wave r2 at --patience 25: five of seventeen
        # games were cut, four at zero levels while holding correct control models. sk48
        # died at turn 26 of an 80 turn budget, with zero deaths, holding a complete
        # strategy: "align the crane centre with a target, extend until contact, then
        # retract to reel that target left."  That is a solved game killed mid-execution.
        #
        # Learning a new rule of the game therefore also counts. It is the right signal
        # rather than simply a bigger number because it still kills the failure patience
        # exists for: the cd82 grind of 66 consecutive turns and ~700 actions learned
        # nothing new, so it would still be cut here, while a slow learner survives.
        # `mechanic()` rejects duplicates, so a claim cannot be re-registered to buy turns,
        # and `unmechanic` shrinking the list can never satisfy `> 0`. A determined agent
        # could still write a slightly different string every turn; `max_turns` remains the
        # hard ceiling for exactly that reason.
        gained = env.best - before_levels
        learned = len(env.mechanics_learned) - before_mechanics
        stale = 0 if (gained > 0 or learned > 0) else stale + 1

        # BOOK THE RESULT AUTOMATICALLY. Gap 10's lesson is that a primitive the agent
        # must remember to call is a primitive that is never called, and `accept()` is
        # the standing proof -- present in the REPL, absent from every trace. So the
        # harness scores the skills itself from what actually happened, rather than
        # asking the agent to be diligent about its own bookkeeping.
        #
        # The signal is deliberately coarse: a skill CALLED on a turn that cleared a
        # level is credited, and one called on a turn that died is charged. That is
        # noisy per turn and correct in aggregate, which is all `available()` needs --
        # it gates transfer on `wins > 0` and retires at four results below a third.
        # A precise attribution would need per-call instrumentation the REPL cannot
        # give without changing what the agent's code means.
        if installed_skills or library.skills:
            called = [n for n in library.skills if n in (code or "")]
            if called and gained > 0:
                for n in called:
                    library.record(n, won=True)
            elif called and env.deaths_this_turn:
                for n in called:
                    library.record(n, won=False)

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
                    "mechanics": list(env.mechanics_learned),
                    # WHETHER THIS GAME DRAWS A MOVE BAR, as measured rather than as
                    # assumed. Eight games are on record as bar-less, but that record
                    # was written by runs whose agents never called clock() -- bp35
                    # went sixteen deaths without asking once. Now that the harness
                    # identifies the bar by watching, the answer is a by-product of
                    # playing, and recording it here settles the question for free
                    # instead of costing another run to ask.
                    "deaths": env.deaths,
                    "bar_row": env._bar_row,
                    "bar_colour": env._bar_colour,
                }) + "\n")

        # CHECKPOINT THE SCORECARD, because until now it was written once, after
        # the run returned, and a run that did not return left nothing at all.
        # Measured today: two runs were stopped deliberately and both vanished --
        # no scorecard, no record that the game had been played. The same hole
        # swallows a crash, a reboot, a killed shell, or an endpoint that stays
        # down past the retry ladder, and each of those costs about two hours and
        # four million tokens. The trace survived every one of those; the result
        # did not, which is backwards -- the trace is the diagnostic and the
        # scorecard is the deliverable.
        #
        # Written whole to a temporary file and moved into place, so a kill
        # landing mid-write cannot leave a half-written JSON file where the
        # standings scorer expects a valid one. A truncated scorecard would be
        # read as a malformed artifact and skipped, which is the same loss with
        # extra steps.
        if out_path:
            snapshot = dict(
                game=game, agent=deployment, levels_completed=env.best,
                win_levels=env.frame().win_levels, actions_spent=env.spent,
                level_actions=env.level_actions, deaths=env.deaths,
                tokens=tokens, elapsed_s=round(time.time() - started, 1),
                seed=seed, turns_used=turn + 1, max_turns=max_turns,
                mechanics_learned=list(env.mechanics_learned),
                bar_row=env._bar_row, bar_colour=env._bar_colour,
                start_level=start_level, scorable=not jumped,
                stopped="in_progress", harness=HARNESS_VERSION,
            )
            try:
                tmp = Path(out_path).with_suffix(".partial")
                tmp.write_text(json.dumps({
                    "agent": deployment, "games": 1,
                    "levels_completed": env.best,
                    "levels_available": env.frame().win_levels,
                    "tokens": tokens, "runs": [snapshot],
                    "harness": HARNESS_VERSION,
                }, indent=2), encoding="utf-8")
                tmp.replace(Path(out_path))
            except OSError:
                # A run must never die because its bookkeeping could not be
                # saved. The trace still has everything needed to reconstruct.
                pass

        print(
            f"  {game} t{turn + 1}: acts={env.spent - before_spent} total={env.spent} "
            f"deaths={env.deaths} lv={env.best}/{env.frame().win_levels} tok={tokens}"
            f"{' ERR' if err else ''}",
            flush=True,
        )

        if env.game_won:
            stopped = "won"
            break
        if env.best >= env.frame().win_levels:
            stopped = "won"
            break
        if stale >= patience:
            stopped = "patience"
            break
        if env.spent >= action_cap:
            stopped = "action_cap"
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
        # WHY the run ended, because "5 of 8" does not say whether the agent ran out of
        # ideas or out of harness. Measured on lp85: it stopped at 5/8 having spent 394
        # actions against a 388-action human baseline for the WHOLE game -- so it was
        # still solving, at roughly human cost, and what ended it was `max_turns`. ARC
        # charges actions, never turns, so a turn-capped run is the harness deciding the
        # score. Without this field that read as a capability ceiling.
        "stopped": stopped,
        "turns_used": turn + 1,
        "max_turns": max_turns,
        "mechanics_learned": list(env.mechanics_learned),
        # Stamped so a debug session cannot be read as a measurement months from now.
        # `scorable` is the field to check before quoting anything from this dict.
        "start_level": start_level,
        "scorable": not jumped,
        # Which harness produced this card. The level counter was treated as monotone
        # until HARNESS_VERSION 2, so every card written before it may charge a level
        # the wrong number of actions -- and no amount of re-reading the file can tell.
        # Stamping forward is the only honest fix: the invariant binds what this build
        # writes, and older cards are quarantined by name rather than silently trusted.
        "harness": HARNESS_VERSION,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="sb26")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-turns", type=int, default=20)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--action-cap", type=int, default=6000)
    ap.add_argument("--exec-timeout", type=float, default=300.0,
                    help="wall-clock seconds a single code block may run before it is "
                         "stopped and reported back to the agent (see CodeTimeout)")
    ap.add_argument("--deployment", default=DEPLOYMENT)
    ap.add_argument("--out", default="")
    ap.add_argument("--trace", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--start-level", type=int, default=1,
        help="DEBUG ONLY: begin on this level. Skipped levels are never credited, so a "
             "jumped run reports scorable=false and must not be quoted as a result.",
    )
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
                 args.action_cap, args.trace, args.seed, args.start_level,
                 # Only checkpoint into the output file when this run owns it. A
                 # multi-game batch shares one path, and a per-turn snapshot of
                 # the game in progress would overwrite the games already
                 # finished -- trading one loss for a worse one.
                 args.out if len(games) == 1 else "",
                 args.exec_timeout)
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
