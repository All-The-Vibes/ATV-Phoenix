"""Can the harness find the move bar without being asked?

Free: no environment, no API, no actions.

`frames.budget` finds a bar-SHAPED row on its own -- full width, one or two
colours, at most two runs -- but a partly-drained bar has two segments and one
frame cannot say which is the budget that remains. It refuses to guess, and
asks the caller to pass back the colour the row showed while the bar was full.

The caller is the agent, so the whole mechanism sat behind the agent's own
curiosity. Measured on bp35: thirty turns, eleven deaths, and not one call to
`clock()` in the entire run. Nothing was handed back, nothing was identified,
and every death notice told the agent "this game DRAWS NO MOVE BAR" while its
own printed output showed row 63 draining 63 -> 43 -> 38 -> 29. The harness had
turned "I could not read this" into "there is nothing here to read" -- the same
failure as `parse` describing one game and answering confidently for the other
twenty-four.

Nothing had to be asked. The harness holds every frame, and across two frames
the ambiguity is gone: the remaining segment loses cells and the spent one
gains them.

The geometry below is bp35's, taken from its trace: a colour-15 background, a
bar on the bottom row that starts as colour 0 and is eaten into from the left.
"""
from __future__ import annotations

import numpy as np

from evals.arc.codeact_agent import Env


def _board(spent_cells: int) -> np.ndarray:
    """bp35's board: c15 everywhere, row 63 a bar of c0 eaten from the left."""
    grid = np.full((64, 64), 15, dtype=np.int8)
    grid[63, :] = 0
    if spent_cells:
        grid[63, :spent_cells] = 15
    return grid


class _FakeEnv:
    """Just enough Env to drive _learn_bar_direction over a scripted sequence."""

    def __init__(self, boards):
        self._boards = boards
        self._i = 0
        self._bar_colour = None
        self._bar_row = None
        self._bar_seen = None

    grid = lambda self: self._boards[self._i]  # noqa: E731
    _learn_bar_direction = Env._learn_bar_direction

    def advance(self):
        self._i += 1
        self._learn_bar_direction()


def check_a_full_bar_names_itself_at_once() -> None:
    """A pristine bar is one full-width run, and that is not ambiguous.

    bp35 opens exactly like this. The reading was always available on frame one;
    nothing in the harness ever took it, because taking it was the agent's job
    and this agent never called clock().
    """
    env = _FakeEnv([_board(0)])
    env._learn_bar_direction()

    assert env._bar_colour == 0, (
        f"a full, single-colour bar was not identified; got {env._bar_colour!r}"
    )
    assert env._bar_row == 63, env._bar_row
    print("  a full bar names itself on frame one        OK")


def check_a_draining_bar_is_identified_unasked() -> None:
    """The harder case: first sight of the board is already mid-drain.

    After a death mid-turn, or on a level whose opening frame is never read, the
    bar is two-toned from the start and no single frame can say which segment is
    the budget. Two frames can.
    """
    env = _FakeEnv([_board(20), _board(25), _board(34)])

    env._learn_bar_direction()
    assert env._bar_colour is None, "concluded from a single ambiguous frame"

    env.advance()

    assert env._bar_colour == 0, (
        f"the draining segment was not identified; got {env._bar_colour!r}. "
        "bp35 died eleven times being told it had no bar at all."
    )
    assert env._bar_row == 63, env._bar_row
    print("  a draining bar names itself in two frames   OK")


def check_a_refill_does_not_name_the_wrong_half() -> None:
    """The bar refills on death and reset, and the movement reverses there.

    Comparing across a refill shows the REMAINING segment growing, which would
    name the spent colour as the budget: a confident reading of the wrong half,
    strictly worse than not knowing. Every rebuild therefore drops the previous
    reading, and this pins that it does.
    """
    env = _FakeEnv([_board(34), _board(20)])
    env._learn_bar_direction()

    # What the death path and reset() do to the cache.
    env._bar_seen = None

    env.advance()
    assert env._bar_colour is None, (
        f"named colour {env._bar_colour!r} the budget by comparing across a refill"
    )
    print("  a refill is not mistaken for a drain        OK")


def check_a_static_row_is_never_named() -> None:
    """Board furniture does not move, so it never satisfies the test.

    cd82 has a static strip drawn in the bar's own two colours which once won
    the search on row index and made clock() report a frozen 18/64 forever. A
    rule that concludes only on observed movement cannot make that mistake.
    """
    env = _FakeEnv([_board(20), _board(20), _board(20)])
    env._learn_bar_direction()
    env.advance()
    env.advance()
    assert env._bar_colour is None, "named a row that never moved"
    print("  an unmoving row is never called a bar       OK")


def check_the_watcher_runs_on_every_change() -> None:
    """The identification is worthless if nothing calls it.

    It is wired into the changed-frame branch of _step rather than into clock(),
    because the game this fixes is precisely the one whose agent never calls
    clock().
    """
    import inspect

    src = inspect.getsource(Env._step)
    assert "_learn_bar_direction()" in src, (
        "the bar watcher is no longer driven from _step, so it only runs when the "
        "agent already thought to look -- which is the bug it exists to fix"
    )
    print("  the watcher is driven by the frame, not the agent  OK")


if __name__ == "__main__":
    print("finding the move bar without being asked:")
    check_a_full_bar_names_itself_at_once()
    check_a_draining_bar_is_identified_unasked()
    check_a_refill_does_not_name_the_wrong_half()
    check_a_static_row_is_never_named()
    check_the_watcher_runs_on_every_change()
    print("ALL GREEN")
