"""The wave selector must stop re-drafting a mined-out game.

ARC Mission Watch, 2026-08-15: ls20 had been drafted nine times for +1.184% total
and was in flight again while untried headroom sat unpicked. The only anti-re-draft
term in rank() was `/(1.0 + 0.5*attempts)`, a blunt count that decays a game's
productive early drafts exactly as hard as its barren recent ones, so a game that
banked its score long ago keeps ranking on next-level headroom it no longer delivers.

This pins the corrected behaviour: a game drafted repeatedly with no rise in its best
is ranked below an untried game that still has real headroom.
"""
import json

import evals.arc.auto_corpus as ac


def _scorecard(directory, name, runs):
    (directory / name).write_text(json.dumps({"runs": runs}), encoding="utf-8")


def test_mined_out_game_ranks_below_untried(tmp_path, monkeypatch):
    results = tmp_path / "arc-results"
    results.mkdir()
    ledger = results / "auto-corpus-ledger.jsonl"

    baselines = {"ls20": [10] * 8, "fresh": [10] * 8}

    # ls20: efficiency-capped at 3/8 (best 0.1917), plus a wide-spread shallow run so
    # the probability term stays high. This is the profile that kept it top-of-board.
    _scorecard(results, "ls20.json", [
        {"game": "ls20", "levels_completed": 3, "start_level": 1,
         "level_actions": [9, 9, 9]},
        {"game": "ls20", "levels_completed": 1, "start_level": 1,
         "level_actions": [400]},
    ])
    # fresh: 1/8 cleared, modest spread, never drafted -- real headroom, no history.
    _scorecard(results, "fresh.json", [
        {"game": "fresh", "levels_completed": 1, "start_level": 1,
         "level_actions": [11]},
        {"game": "fresh", "levels_completed": 1, "start_level": 1,
         "level_actions": [18]},
    ])

    # ls20 drafted nine times, best flat at its ceiling on every draft -> barren.
    with ledger.open("w", encoding="utf-8") as fh:
        for _ in range(9):
            fh.write(json.dumps({
                "event": "wave", "games": ["ls20"],
                "why": {"ls20": {"best": 0.1917}},
            }) + "\n")

    monkeypatch.setattr(ac, "RESULTS", results)
    monkeypatch.setattr(ac, "LEDGER", ledger)

    order = [game for _, game, _ in ac.rank(baselines)]
    assert order.index("fresh") < order.index("ls20"), (
        f"mined-out ls20 must rank below untried fresh; got {order}")


def test_productive_game_is_not_benched(tmp_path, monkeypatch):
    """A game whose best keeps rising must not be penalised as if it were mined out."""
    results = tmp_path / "arc-results"
    results.mkdir()
    ledger = results / "auto-corpus-ledger.jsonl"

    baselines = {"riser": [10] * 8}

    _scorecard(results, "riser.json", [
        {"game": "riser", "levels_completed": 3, "start_level": 1,
         "level_actions": [9, 9, 9]},
    ])

    # best rose on every draft -> no barren streak -> no extra decay.
    rising = [0.02, 0.06, 0.1917]
    with ledger.open("w", encoding="utf-8") as fh:
        for best in rising:
            fh.write(json.dumps({
                "event": "wave", "games": ["riser"],
                "why": {"riser": {"best": best}},
            }) + "\n")

    monkeypatch.setattr(ac, "RESULTS", results)
    monkeypatch.setattr(ac, "LEDGER", ledger)

    assert ac.barren_streaks().get("riser", 0) == 0
