"""Issue #183: the environment-characterisation primitive has to answer WHICH region changed.

These pin the four properties the ARC traces show were missing, in a domain the module has never
seen: a fake environment built here, not an ARC grid loaded from a fixture.
"""
from __future__ import annotations

import pytest

from phoenix_learn.discover import Characterisation, characterise, diff_regions, digest


class Grid:
    """A 4x4 board. Action 0 flips one cell, 1 flips the same cell, 2 does nothing, 3 repaints."""

    def __init__(self):
        self.cells = [[0] * 4 for _ in range(4)]
        self.applied = 0

    def snapshot(self):
        return [row[:] for row in self.cells]

    def reset(self):
        self.cells = [[0] * 4 for _ in range(4)]

    def apply(self, action):
        self.applied += 1
        if action in (0, 1):
            self.cells[2][3] = 1
        elif action == 2:
            pass
        elif action == 3:
            self.cells = [[9] * 4 for _ in range(4)]


def test_inert_action_is_named_so_one_press_disproves_it():
    env = Grid()
    c = characterise([0, 1, 2, 3], env.snapshot, env.apply, reset=env.reset)
    assert c.inert == (2,)
    assert c.active == (0, 1, 3)


def test_region_is_the_changed_cells_not_the_whole_board():
    env = Grid()
    c = characterise([0, 3], env.snapshot, env.apply, reset=env.reset)
    assert c.regions_for(0) == (("cells", 2, 3, 2, 3, 1),)
    assert c.regions_for(3) == (("cells", 0, 0, 3, 3, 16),)


def test_cost_is_one_action_per_action():
    env = Grid()
    c = characterise([0, 1, 2, 3], env.snapshot, env.apply, reset=env.reset)
    assert c.actions_spent == 4
    assert env.applied == 4


def test_aliases_need_a_reset_and_say_so_when_they_do_not_have_one():
    env = Grid()
    with_reset = characterise([0, 1, 2, 3], env.snapshot, env.apply, reset=env.reset)
    assert with_reset.aliases_known is True
    assert (0, 1) in with_reset.aliases

    env2 = Grid()
    without = characterise([0, 1, 2, 3], env2.snapshot, env2.apply)
    assert without.independent is False
    assert without.aliases_known is False
    assert without.aliases == ()


def test_sequential_run_reports_the_second_press_as_inert():
    env = Grid()
    c = characterise([0, 1], env.snapshot, env.apply)
    assert c.inert == (1,)


class Shell:
    """State is a mapping, the shape a shell agent sees: files plus running processes."""

    def __init__(self):
        self.state = {"files": ("a.txt",), "procs": (11,)}

    def snapshot(self):
        return {k: v for k, v in self.state.items()}

    def reset(self):
        self.state = {"files": ("a.txt",), "procs": (11,)}

    def apply(self, action):
        if action == "touch":
            self.state["files"] = ("a.txt", "b.txt")
        elif action == "spawn":
            self.state["procs"] = (11, 12)
        elif action == "noop":
            pass


def test_same_primitive_characterises_a_mapping_state():
    env = Shell()
    c = characterise(["touch", "spawn", "noop"], env.snapshot, env.apply, reset=env.reset)
    assert c.inert == ("noop",)
    assert c.regions_for("touch") == (("key", "files"),)
    assert c.regions_for("spawn") == (("key", "procs"),)


def test_diff_regions_on_flat_sequences_and_scalars():
    assert diff_regions([1, 2, 3], [1, 5, 3]) == (("index", 1),)
    assert diff_regions([1, 2], [1, 2]) == ()
    assert diff_regions("left", "right") == (("value",),)


def test_digest_is_stable_across_equal_values_and_key_order():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert digest([1, 2]) != digest([2, 1])


def test_regions_for_rejects_an_action_that_was_never_pressed():
    env = Grid()
    c = characterise([0], env.snapshot, env.apply, reset=env.reset)
    with pytest.raises(KeyError):
        c.regions_for(3)


def test_characterisation_is_a_frozen_record():
    env = Grid()
    c = characterise([0], env.snapshot, env.apply, reset=env.reset)
    assert isinstance(c, Characterisation)
    with pytest.raises(Exception):
        c.actions_spent = 99
