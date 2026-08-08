"""The ARC-AGI-3 meter must discriminate (issue #177).

The Tier 3 evaluation this exists to supplement is saturated at 1.0 with n=9, so
it cannot separate a good change from a bad one (#142, #171). A replacement meter
earns its place only by showing it can tell two policies apart. That is the
property pinned here, not a score.

The recorded-result tests always run. The live test needs the ``arc-agi`` package
and the downloaded environments, so it skips when either is missing rather than
failing a machine that never opted into the benchmark.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "arc-results"
CORPUS_LEVELS = 183  # 25 environments; matches the published benchmark size


def _load(name: str) -> dict:
    """Read a recorded run.

    A missing file is a failure, not a skip. These results are committed the same
    way `eval/scoreboard.json` is, so their absence means the meter never ran, and
    a suite that skips its way to exit 0 is the precise defect #172 fixed in CI:
    a green that proved nothing.
    """
    path = RESULTS / name
    assert path.exists(), f"no recorded run at {path}; the meter has not been run"
    return json.loads(path.read_text(encoding="utf-8"))


def test_corpus_is_the_whole_benchmark():
    """A meter measured on a subset would silently shrink its own denominator."""
    novelty = _load("novelty.json")
    assert novelty["games"] == 25
    assert novelty["levels_available"] == CORPUS_LEVELS


def test_no_step_errors():
    """Click environments raise KeyError: 'x' when ACTION6 is stepped without
    coordinates. Four environments were lost to that before policies.py supplied
    them, and a run that silently swallows those is measuring a smaller corpus
    than it reports."""
    for name in ("null.json", "novelty.json"):
        assert _load(name)["step_errors"] == 0, f"{name} lost steps to errors"


def test_meter_discriminates_between_policies():
    """The whole point. If a do-nothing policy and an exploring policy score the
    same, this instrument is as blind as the one it supplements."""
    null = _load("null.json")
    novelty = _load("novelty.json")
    assert novelty["levels_completed"] > null["levels_completed"], (
        f"novelty {novelty['levels_completed']} did not beat "
        f"null {null['levels_completed']}; the meter cannot discriminate"
    )


def test_headroom_remains():
    """A meter with no headroom is the failure mode being replaced."""
    novelty = _load("novelty.json")
    assert novelty["levels_completed"] < novelty["levels_available"], (
        "novelty solved the corpus, which would mean this meter is already saturated"
    )


@pytest.mark.parametrize("policy,expected_floor", [("null", 0), ("novelty", 1)])
def test_live_run_is_reproducible(policy, expected_floor):
    """Replay a short live run and confirm the harness still reaches the floor."""
    pytest.importorskip("arc_agi")
    import arc_agi

    from evals.arc.run_arc import play

    arc = arc_agi.Arcade()
    available = {e.game_id.split("-")[0] for e in arc.get_environments()}
    if "sp80" not in available:
        pytest.skip("sp80 environment not downloaded")

    run = play(arc, "sp80", policy, budget=2000, seed=0)
    assert run["step_errors"] == 0
    assert run["levels_completed"] >= expected_floor


def test_heldout_split_shares_no_game():
    """A game on two sides of the wall is leakage, and it is the exact thing the
    gate exists to prevent. Seeds multiply n inside a split; they never cross one."""
    gate = _load("gate.json")
    public = set(gate["split"]["public"])
    dev = set(gate["split"]["dev"])
    private = set(gate["split"]["private"])
    assert not public & private, f"leaked into private: {public & private}"
    assert not dev & private, f"leaked into private: {dev & private}"
    assert not public & dev, f"leaked into dev: {public & dev}"


def test_heldout_gate_had_enough_evidence_to_decide():
    """n below ADOPT_MIN_N returns EXPERIMENTAL_SMOKE_TEST, which is a refusal to
    judge rather than a judgement. The point of this meter is having enough rows to
    actually decide, which the n=9 Tier 3 evaluation does not."""
    from phoenix_learn.gate import ADOPT_MIN_N

    gate = _load("gate.json")
    assert gate["private_n"] >= ADOPT_MIN_N, (
        f"private_n {gate['private_n']} is below ADOPT_MIN_N {ADOPT_MIN_N}, "
        "so the verdict is a shrug, not a decision"
    )
    assert gate["decision"] != "EXPERIMENTAL_SMOKE_TEST"


def test_selection_split_performance_is_not_evidence():
    """The recorded run caught the failure this whole step exists for: a candidate
    that beat the baseline on the selection split and delivered nothing on games it
    had never seen. If the gate ever adopts on that shape, it has stopped working."""
    gate = _load("gate.json")
    selected = gate["selected"]
    dev_acc = gate["dev_selection"][selected]["acc"]
    baseline_dev_acc = gate["dev_selection"][gate["baseline"]]["acc"]

    if dev_acc > baseline_dev_acc:
        held_out_gain = gate["selected_private_acc"] - gate["gen0_private_acc"]
        if held_out_gain <= 0:
            assert gate["decision"] != "ADOPT_ELIGIBLE", (
                f"{selected} beat the baseline on dev ({dev_acc} vs {baseline_dev_acc}) "
                f"and gained {held_out_gain} on held-out games, yet the gate adopted it"
            )
