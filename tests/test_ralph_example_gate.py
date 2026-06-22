"""Acceptance check for issue #9 — fix vacuously-green done-check.example.json.

The shipped example gates on ["npm","test"] which exits 0 on a fresh scaffold,
making it a vacuous gate that the driver's own baseline guard correctly rejects.
The fix: replace with a content-asserting example + add README guidance.

Done-check: pytest tests/test_ralph_example_gate.py exits 0.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "dist" / "ralph" / "done-check.example.json"
README = ROOT / "dist" / "ralph" / "README.md"


def _example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_example_is_valid_json() -> None:
    """done-check.example.json must be valid JSON."""
    data = _example()
    assert isinstance(data, dict), "example must be a JSON object"


def test_example_kind_is_command_exit() -> None:
    """example must use kind=command_exit (the recommended gate type)."""
    assert _example().get("kind") == "command_exit"


def test_example_not_bare_build_or_test_runner() -> None:
    """The example must NOT be a bare build/test runner (npm test, pnpm build, etc.).

    Bare runners exit 0 on empty projects — they are vacuously green from the start
    and the driver's baseline guard will reject them. The example must demonstrate a
    content-asserting gate that starts RED on a fresh scaffold.
    """
    target = _example().get("target", [])
    # Bare patterns that are vacuously green on fresh scaffolds:
    vacuous = [
        ["npm", "test"],
        ["npm", "run", "test"],
        ["pnpm", "test"],
        ["pnpm", "run", "test"],
        ["yarn", "test"],
        ["npm", "run", "build"],
        ["pnpm", "build"],
    ]
    assert target not in vacuous, (
        f"Example target {target!r} is a bare build/test runner — vacuously green "
        "on a fresh scaffold. Replace with a content-asserting gate (e.g. a specific "
        "test file, a regex_in_file check, or a verify script that asserts artifacts "
        "contain expected content)."
    )


def test_example_comment_warns_vacuous() -> None:
    """Example JSON comment must explain the vacuous-gate pitfall."""
    comment = _example().get("_comment", "")
    keywords = ["red", "start", "fail"]
    assert any(kw in comment.lower() for kw in keywords), (
        f"Example _comment must explain that the gate must start RED (fail). Got: {comment!r}"
    )


def test_readme_warns_vacuous_gates() -> None:
    """README must explicitly warn that bare build/test is usually vacuously green."""
    readme = _readme()
    assert "vacuous" in readme.lower() or "already green" in readme.lower(), (
        "README must mention the vacuous-gate pitfall (bare build/test exits 0 on "
        "fresh scaffold). Add a note near the done-check.json contract section."
    )