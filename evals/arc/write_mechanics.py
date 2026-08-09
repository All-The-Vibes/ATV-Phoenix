"""Rewrite the sb26 mechanics note with the MEASURED cost model.

The note is injected into every turn, so a wrong sentence in it is paid for on every turn
of every run. The row-53 claim was wrong in the most expensive possible direction: it told
the agent the bar was a clock draining "as ticks pass" and to budget its turn against it.
Measured against the live game, the bar only moves on a DROP or a SUBMIT. Looking, picking
up, undoing and clicking empty space are all free.

Run this once; it edits eval/arc-results/mechanics.json in place.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "eval" / "arc-results" / "mechanics.json"

TEXT = """MECHANICAL FACTS. These are how the GAME and the harness behave -- things that are
  invisible on screen and would otherwise cost actions, or deaths, to discover. None of
  them says which colour belongs on which pad on any level; that is the puzzle, and it is
  yours.

  SUBMIT IS action 5. Arranging the pieces correctly does NOT complete a level. Nothing
  happens until you press(5). Verified by experiment: with a level arranged correctly,
  press(7) does not clear it and a stray click does not clear it, but press(5) clears it
  immediately. Earlier runs arranged a board perfectly, saw no completion, concluded the
  arrangement must be wrong, and burned thousands of actions permuting a board that was
  already right. If you have placed every piece and nothing happened, press(5) BEFORE you
  change anything.

  DRAG AND DROP: click a tray piece to pick it up, then click a destination pad to drop
  it. Clicking a destination alone does nothing.

  ACTION 7 IS UNDO, and it is inert on the first level. With pieces on the board, each
  press(7) sends the most recently placed piece back to the tray, last in first out.
  Measured: six presses removed six pieces one at a time. Use it to correct a single
  misplacement instead of rebuilding.

  THE BAR ON ROW 53 IS A MOVE BUDGET, NOT A TIMER. This note used to call it a countdown
  that drained on its own as the turn went by. That was wrong, and it was the most
  expensive error in this file. Measured directly against the live game, cell by cell:

      click a tray piece (pick up) ..... 0
      click a pad (DROP a piece) ....... 1
      press(5) submit .................. 1
      press(7) undo .................... 0
      click empty space ................ 0
      thinking, reading, doing nothing .. 0
      click a piece ALREADY ON A PAD ... 0   (it comes back into your hand)

  120 clicks on empty space did not move it. 199 undos did not move it. 64 consecutive
  submits took it from full to empty and the 64th killed. It counts pieces DROPPED and
  boards SUBMITTED, and nothing else.

  Three consequences, and they change how a turn should be planned:

    LOOKING IS FREE. grid(), objects(), board(), layout(), diff, picking a piece up and
    putting it back -- none of it costs a cell. There is no reason to hurry a read.

    A HYPOTHESIS COSTS (pads + 1) CELLS. Eight pads means nine cells per full attempt, so
    a 64-cell bar affords SEVEN attempts before you die and the level restarts. A measured
    run planned six attempts per turn on level 7, died once per turn for seven turns, and
    spent 1,367 actions there. It was not out of ideas; it was out of budget and could not
    see the meter.

    A DIFFERENTIAL TEST IS FAR CHEAPER THAN A REBUILD, and this is the biggest lever on
  a level you are searching. A piece that is ALREADY ON A PAD can be picked up again by
  clicking it -- that costs nothing -- and dropped somewhere else for one cell. Dropping
  onto an OCCUPIED pad is accepted, also for one cell. So the price of your SECOND
  hypothesis is the number of pads whose colour CHANGED, plus one for the submit. Not
  eight.

  Measured on the live game: pick up a placed piece = 0 cells, re-drop it = 1 cell, drop
  onto an occupied pad = 1 cell, undo = 0 cells.

  On an eight-pad level that is the difference between 7 hypotheses per life and roughly
  20, because candidates worth testing next usually differ from the last one on two or
  three pads. Rebuilding the whole board to test a two-pad change wastes six cells every
  time. Order the assignments you want to try so that consecutive ones are close, and pay
  only for the difference.

  clock() READS THE BAR and costs no action. It returns cells left, used, total and the
  fraction remaining, taken from the drawing rather than from a remembered constant --
  bar length is a per-level property. Call it before you plan a turn and divide.

  seated() TELLS YOU WHICH COLOUR IS ON WHICH PAD right now, also for no action.

  try_assignment(mapping) PLAYS A HYPOTHESIS FOR THE FEWEST CELLS, and on a level you are
  searching it is the difference between seven attempts per life and roughly twenty. Hand
  it either shape you already write -- a list of (colour, (x, y)) pairs, or a
  {(x, y): colour} dict -- and it puts the board into that state and submits. What it does
  NOT do is choose the mapping; that is your hypothesis and it stays entirely yours.

  It is cheap because it only pays for the pads whose colour must CHANGE. Every candidate
  is a permutation of the same tray, so it reaches the next one by SWAPS, and one swap
  fixes a pad for one cell. Two candidates differing on two pads cost 1 swap + 1 submit =
  2 cells, where tearing the board down and rebuilding it costs 9. It returns cells_spent,
  cells_left, whether the arrangement was achieved, and whether it won. So ORDER the
  candidates you mean to try so that consecutive ones are close, and pay only for the
  differences.

  DEATH INTERRUPTS YOUR CODE. When the bar empties, the level restarts: every piece
  returns to the tray and the bar refills. Your running code is cut off at that point and
  told, rather than being allowed to carry on against a board it no longer understands.

  A DEATH IS CHEAP, AND THE BAR IS A RESOURCE TO SPEND RATHER THAN HOARD. The restart
  gives you the SAME level -- same clues, same tray, same pads -- with a FULL bar. You are
  scored on levels cleared and actions spent, and on nothing else: dying is not penalised
  beyond the actions it already cost you. Every assignment the board has refused is
  remembered for you across the restart, so no knowledge is lost either. A measured run
  drew the wrong conclusion from this and it was expensive: with ten cells left and nine
  needed per attempt, it spent three consecutive turns re-proposing candidates it had
  already been refused, protecting a bar that was worth less than one test. If the bar
  cannot fund an attempt worth making, drain it and take the restart.

  PLACEMENT ORDER DOES NOT MATTER. The board is scored as a MAPPING -- which colour ends
  up on which pad -- and not as a path through the pads. Measured offline against the live
  game: a winning assignment was replayed with its placement sequence randomly shuffled,
  three shuffles each on three different levels, and all nine cleared.
  So searching over traversal orders searches a space that is factorially too large and
  almost entirely made of duplicates: two different 'routes' that put the same colour on
  the same pad ARE THE SAME ANSWER and the board cannot tell them apart. A measured run
  spent thirteen turns and a million tokens on one level and tested only three distinct
  assignments, because it was reasoning about the order to walk the pads in.
  Ask WHICH CLUE BELONGS ON WHICH PAD. Do not ask in what order to walk them.
  Make each attempt rule out a family of answers rather than a single arrangement,
  because the bar charges you per attempt.

  THE CLUE ROW IS NOT ALWAYS ONE RING PER PAD. Some levels draw more rings than there are
  pads, some fewer, and on those levels the ring colours do not match the tray as a
  multiset. CHECK the counts rather than assuming; writing `assert len(clues) ==
  len(pads)` and giving up when it fails is a measured failure mode that cost several runs
  a whole level. layout()["clue_structure"] reports the SHAPE of the row -- whether it is
  one ring per pad, and if a contiguous block of colours repeats, which block and where.
  It does not tell you what the row MEANS. Which pads a reduced row addresses, which pads
  take a block, and what colour belongs on a collapsed position are yours to work out, and
  the tray is the lever: it holds exactly one piece per pad, so whatever it has left over
  once the spelled-out colours are accounted for is what the gaps take.

  grid() IS STALE FOR ONE FRAME after a level change. The first read on a new level can
  still show the old board. Spend one action, then re-read before you trust coordinates."""


def main() -> int:
    known = {}
    if PATH.exists():
        try:
            known = json.loads(PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            known = {}
    known["sb26"] = TEXT
    PATH.write_text(json.dumps(known, indent=2), encoding="utf-8")
    print(f"wrote {PATH} ({len(TEXT)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
