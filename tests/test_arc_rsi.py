"""The RSI ARC loop must keep what it learns (issue #177 follow-on).

Four agent designs were measured against ARC-AGI-3 today and three scored zero. The
differences were not tuning, they were structural, and each fix is pinned here so a
future edit cannot quietly undo one:

* the agent must see an image, because a text sketch of a 64x64 grid destroys the
  spatial structure the benchmark tests
* the mechanical probe must find drag-and-drop without a model, because that fact is
  what turns an unsolvable board into a nine-action solve
* a skill that worked must survive into the next run, because re-deriving the rules
  every turn is what the first three agents did
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "arc-results"


def _load(name: str) -> dict:
    path = RESULTS / name
    assert path.exists(), f"no recorded run at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_rsi_agent_beat_the_model_free_floor_on_its_game():
    """The floor for sb26 under count-based exploration is zero levels."""
    run = _load("rsi-sb26.json")
    assert run["levels_completed"] >= 1, "RSI agent did not clear a level"
    assert run["runs"][0]["game"] == "sb26"


def test_rsi_agent_records_how_it_played():
    """A number with no method behind it cannot be checked later."""
    run = _load("rsi-sb26.json")
    assert run["action_space"] == "executable_python"
    assert run["probe"] == "mechanical"
    assert run["skill_library"] is True
    assert run["auth"] == "managed_identity"


def test_a_skill_was_learned_and_survived():
    """The skill library is the RSI claim. An empty library means nothing compounded."""
    library = _load("skills.json")
    skills = library["skills"]
    assert skills, "no skill was ever saved"
    winners = [s for s in skills if s["wins"] > 0]
    assert winners, "no saved skill has ever won a level"


def test_learned_skill_reads_the_board_instead_of_hardcoding():
    """A skill full of literal coordinates solves exactly one level and no more.
    The one that works parses the grid, which is why it transfers."""
    library = _load("skills.json")
    winners = [s for s in library["skills"] if s["wins"] > 0]
    source = "\n".join(s["source"] for s in winners)
    assert "grid()" in source, "winning skill never reads the board"
    assert "np.unique" in source or "np.where" in source, (
        "winning skill does no board analysis, so it cannot generalise"
    )


def test_prober_finds_drag_and_drop_without_a_model():
    """The whole mechanic of sb26, discovered mechanically at zero token cost.

    The destination is invisible to a plain click sweep: clicking an empty tray slot
    changes nothing. It only answers once a piece is held, so the probe has to pick a
    source up first and then sweep. Getting that order wrong is why the first version
    of the prober reported no drag-and-drop on a game that is entirely drag-and-drop.
    """
    pytest.importorskip("arc_agi")
    import arc_agi

    from evals.arc.codeact_agent import Env
    from evals.arc.prober import probe

    arc = arc_agi.Arcade()
    if "sb26" not in {e.game_id.split("-")[0] for e in arc.get_environments()}:
        pytest.skip("sb26 not downloaded")

    raw = arc.make("sb26", include_frame_data=True)
    env = Env(raw, raw.reset())
    report = probe(env, click_step=8)

    assert report["click_rows"], "probe found no clickable cells on a click game"
    assert report["drag_and_drop"], "probe missed drag-and-drop on sb26"
    finding = report["drag_and_drop"][0]
    assert finding["paired_cells"] > finding["solo_cells"], (
        "reported a drag that does no more than clicking the destination alone"
    )
