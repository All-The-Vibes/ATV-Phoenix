"""Contract tests for the phoenix-deps skill.

The skill's whole claim is that dependency work gets an objective gate instead of a
self-graded assertion. A test that only checked "the file exists" would be the same
defect one level up -- a gate that cannot fail. So this asserts the skill is (a)
doctor-valid, (b) actually routed, and (c) carries the enforceable content, and every
assertion is paired with a negative fixture proving it can fail.
"""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "phoenix-deps" / "SKILL.md"
ROUTER = ROOT / "skills" / "phoenix" / "SKILL.md"


def _flat(text: str) -> str:
    """Collapse whitespace so a rule split across a line wrap still matches."""
    return re.sub(r"\s+", " ", text)


def frontmatter_lines(text: str) -> list[str]:
    """Return the lines between the first two `---` fences."""
    lines: list[str] = []
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            return lines
        if in_fm:
            lines.append(line)
    raise AssertionError("frontmatter not closed with `---`")


def assert_doctor_valid_frontmatter(dir_name: str, text: str) -> None:
    """Mirror `src/doctor.rs::check_skill_file` so drift fails pytest, not only cargo."""
    assert text.lstrip().startswith("---"), "missing opening `---` frontmatter"
    fields = frontmatter_lines(text)

    name = next(
        (line.strip()[len("name:") :].strip() for line in fields if line.strip().startswith("name:")),
        None,
    )
    assert name is not None, "missing `name:`"
    assert name == dir_name, f"name '{name}' != directory '{dir_name}'"

    desc = next(
        (
            line.strip()[len("description:") :].strip()
            for line in fields
            if line.strip().startswith("description:")
        ),
        None,
    )
    assert desc is not None, "missing `description:`"
    assert len(desc) >= 20, "description too short (<20 chars)"
    if desc[:1] not in {'"', "'", "|", ">"}:
        assert ": " not in desc, "unquoted description contains `: `, which is invalid YAML"


def assert_enforceable_body(text: str) -> None:
    """The skill must carry runnable/enforceable content, not just prose about hygiene."""
    flat = _flat(text)
    required = {
        "command_exit gate": r'\{\s*"check"\s*:\s*\{\s*"kind"\s*:\s*"command_exit"',
        "clean-room install": r"npm ci|--frozen-lockfile|--immutable|cargo build --locked|--locked-mode|uv sync --locked",
        "no-op boundary": r"no branch,? no commit,? no pull request",
        "blocked disclosure": r"BLOCKED",
        "coverage beside result": r"report coverage beside the result",
        "exploitation ranking": r"Known Exploited Vulnerabilities|KEV catalog",
        "no force flag": r"[Nn]ever `?--force",
    }
    missing = [name for name, pattern in required.items() if not re.search(pattern, flat)]
    assert not missing, f"skill body missing enforceable content: {', '.join(missing)}"


def assert_routed(router_text: str) -> None:
    """An unrouted skill is the repo's costliest defect class: built, wired to nothing."""
    assert "phoenix-deps" in router_text, (
        "phoenix-deps is absent from the meta-skill router, so nothing routes to it"
    )


# --- the real artifacts -------------------------------------------------------------


def test_skill_file_exists():
    assert SKILL.is_file(), f"missing skill file: {SKILL}"


def test_skill_frontmatter_is_doctor_valid():
    assert_doctor_valid_frontmatter("phoenix-deps", SKILL.read_text(encoding="utf-8"))


def test_skill_body_is_enforceable():
    assert_enforceable_body(SKILL.read_text(encoding="utf-8"))


def test_skill_is_routed_from_the_meta_skill():
    assert_routed(ROUTER.read_text(encoding="utf-8"))


def test_skill_credits_its_upstream_license():
    """deps-doctor is MIT; attribution is required and the charter explicitly allows it."""
    flat = _flat(SKILL.read_text(encoding="utf-8"))
    assert "jongio/skills" in flat and "MIT" in flat, "missing upstream attribution"


# --- negative fixtures: prove each assertion can fail --------------------------------


def test_missing_name_fails():
    with pytest.raises(AssertionError, match="missing `name:`"):
        assert_doctor_valid_frontmatter(
            "phoenix-deps", "---\ndescription: a description that is comfortably long enough\n---\nbody"
        )


def test_name_mismatch_fails():
    with pytest.raises(AssertionError, match="!= directory"):
        assert_doctor_valid_frontmatter(
            "phoenix-deps",
            "---\nname: wrong-name\ndescription: a description that is comfortably long enough\n---\nbody",
        )


def test_short_description_fails():
    with pytest.raises(AssertionError, match="too short"):
        assert_doctor_valid_frontmatter("phoenix-deps", "---\nname: phoenix-deps\ndescription: deps\n---\nbody")


def test_unquoted_colon_description_fails():
    with pytest.raises(AssertionError, match="invalid YAML"):
        assert_doctor_valid_frontmatter(
            "phoenix-deps",
            "---\nname: phoenix-deps\ndescription: deps hygiene: the install is the gate and this is long\n---\nbody",
        )


def test_unclosed_frontmatter_fails():
    with pytest.raises(AssertionError, match="not closed"):
        assert_doctor_valid_frontmatter("phoenix-deps", "---\nname: phoenix-deps\nbody without a close")


@pytest.mark.parametrize(
    "body, missing",
    [
        ("prose about dependencies with no gate at all", "command_exit gate"),
        (
            '{"check":{"kind":"command_exit","target":["npm","ci"]}} '
            "no branch, no commit, no pull request BLOCKED "
            "report coverage beside the result KEV catalog never `--force",
            "clean-room install",
        ),
        (
            '{"check":{"kind":"command_exit","target":["npm","ci"]}} npm ci BLOCKED '
            "report coverage beside the result KEV catalog never `--force",
            "no-op boundary",
        ),
        (
            '{"check":{"kind":"command_exit","target":["npm","ci"]}} npm ci '
            "no branch, no commit, no pull request BLOCKED KEV catalog never `--force",
            "coverage beside result",
        ),
        (
            '{"check":{"kind":"command_exit","target":["npm","ci"]}} npm ci '
            "no branch, no commit, no pull request BLOCKED "
            "report coverage beside the result never `--force",
            "exploitation ranking",
        ),
    ],
)
def test_body_missing_required_content_fails(body, missing):
    with pytest.raises(AssertionError, match=re.escape(missing)):
        assert_enforceable_body(body)


def test_prose_mentioning_a_gate_without_a_runnable_check_fails():
    """'Run an objective check' as advice is exactly what this skill exists to replace."""
    with pytest.raises(AssertionError, match="command_exit gate"):
        assert_enforceable_body(
            "Always run an objective phoenix_sense check before claiming the dependency update is done."
        )


def test_unrouted_skill_fails():
    with pytest.raises(AssertionError, match="absent from the meta-skill router"):
        assert_routed("Task arrives\n  -> phoenix-build\n  -> phoenix-craft\n")
