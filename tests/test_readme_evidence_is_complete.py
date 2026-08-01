"""The README evidence table must include results that cut against the thesis.

On 2026-08-01 the table listed five evaluations, all favourable, while eval/scoreboard.json
held a north_star baseline where Phoenix scored below control: arm_a 0.35, arm_b 0.25 over 20
instances on gpt-5.1. The README mentioned north_star zero times.

A project whose thesis is evidence over self-report cannot publish only the wins. This guard
keeps the unfavourable number in the table.

It also pins the phoenix_accept claim. The gate rejects a check never observed failing, which
is verifiable and true. It does not detect a test that asserts its own fixtures: PR #130 got a
legitimate red to green because RED came from the file not existing. Saying it "rejects vacuous
checks" claims more than the code does.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
SCOREBOARD = REPO_ROOT / "eval" / "scoreboard.json"


def test_readme_publishes_the_north_star_result():
    text = README.read_text(encoding="utf-8")
    board = json.loads(SCOREBOARD.read_text(encoding="utf-8"))
    north = board["baseline"]["north_star"]
    arm_a = str(north["arm_a_resolved"])
    arm_b = str(north["arm_b_resolved"])
    assert "north star" in text.lower() or "north_star" in text
    assert arm_a in text, f"README omits the control score {arm_a} from eval/scoreboard.json"
    assert arm_b in text, f"README omits the Phoenix score {arm_b} from eval/scoreboard.json"


def test_readme_says_phoenix_scored_below_control_there():
    text = README.read_text(encoding="utf-8")
    board = json.loads(SCOREBOARD.read_text(encoding="utf-8"))
    north = board["baseline"]["north_star"]
    assert north["arm_b_resolved"] < north["arm_a_resolved"], (
        "scoreboard changed: this guard assumes north_star is the unfavourable result"
    )
    assert "below" in text.lower(), "README must state plainly that Phoenix scored lower"


def test_readme_does_not_overstate_what_accept_rejects():
    text = README.read_text(encoding="utf-8")
    assert "rejects vacuous checks" not in text, (
        "phoenix_accept rejects checks never observed failing. It cannot detect a test that "
        "asserts its own fixtures. See issue #139 and the guard in "
        "tests/test_e2e_proof_is_not_vacuous.py."
    )
