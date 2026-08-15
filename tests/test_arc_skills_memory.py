from __future__ import annotations

import json

from evals.arc.skills import SkillLibrary


def test_a_skill_asserted_without_failure_first_evidence_is_not_stored(tmp_path):
    path = tmp_path / "skills.json"
    library = SkillLibrary(path)

    library.add(
        "read_board",
        "sb26",
        "def read_board():\n    return 1\n",
        "read the board",
        ["general"],
    )

    assert library.available("sb26") == []
    assert not path.exists() or json.loads(path.read_text(encoding="utf-8"))["skills"] == []


def test_a_skill_is_admitted_after_red_then_green_and_carries_evidence(tmp_path):
    path = tmp_path / "skills.json"
    library = SkillLibrary(path)
    library.add(
        "read_board",
        "sb26",
        "def read_board():\n    return 1\n",
        "read the board",
        ["general"],
        when_to_invoke="when the board has to be parsed",
    )

    library.record("read_board", won=False)
    assert library.available("sb26") == []

    library.record("read_board", won=True)

    available = library.available("sb26")
    assert [skill.name for skill in available] == ["read_board"]
    evidence = library.evidence("read_board")
    assert evidence["trials"] == [False, True]
    assert evidence["verdict"]["ok"] is True
    assert evidence["scope"] == "arc:corpus"

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["skills"][0]["trials"] == [False, True]
    assert raw["skills"][0]["verdict"]["ok"] is True
    assert raw["facts"], "skills must be persisted as memory facts as well as legacy rows"


def test_legacy_skills_load_but_only_gate_passing_rows_are_offered(tmp_path):
    path = tmp_path / "skills.json"
    path.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "vacuous",
                        "game": "sb26",
                        "source": "def vacuous():\n    return 1\n",
                        "description": "only ever won in the old file",
                        "wins": 1,
                        "losses": 0,
                        "tags": ["general"],
                    },
                    {
                        "name": "read_board",
                        "game": "sb26",
                        "source": "def read_board():\n    return 1\n",
                        "description": "earned in the old aggregate format",
                        "wins": 1,
                        "losses": 1,
                        "tags": ["general"],
                        "when_to_invoke": "when parsing is needed",
                    },
                    {
                        "name": "solve_sb26_level",
                        "game": "sb26",
                        "source": "def solve_sb26_level():\n    return 1\n",
                        "description": "one-game solver",
                        "wins": 1,
                        "losses": 1,
                        "tags": ["general"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    library = SkillLibrary(path)

    assert [skill.name for skill in library.available("sb26")] == [
        "read_board",
        "solve_sb26_level",
    ]
    assert [skill.name for skill in library.available("bp35", ["general"])] == ["read_board"]
    assert "USE WHEN: when parsing is needed" in library.describe("bp35", ["general"])
