from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
SKILL_DIR = ROOT / ".github" / "skills" / "showoff"
SKILL = SKILL_DIR / "SKILL.md"


def test_showoff_skill_is_portable_to_copilot_hosts() -> None:
    text = SKILL.read_text(encoding="utf-8")
    frontmatter = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)

    assert frontmatter is not None
    metadata = frontmatter.group(1)
    assert re.search(r"^name:\s*showoff\s*$", metadata, re.MULTILINE)
    assert "GitHub Copilot CLI" in text
    assert "VS Code Copilot agent mode" in text
    assert "subagents are optional" in text

    description = re.search(
        r"^description:\s*>\s*\n(?P<body>(?:^  .*\n?)+)", metadata, re.MULTILINE
    )
    assert description is not None
    description_text = re.sub(r"^  ", "", description.group("body"), flags=re.MULTILINE)
    assert len(" ".join(description_text.split())) <= 1024

    markdown = "\n".join(
        path.read_text(encoding="utf-8") for path in SKILL_DIR.rglob("*.md")
    )
    forbidden = (
        "CLAUDE_SKILL_DIR",
        "$ARGUMENTS",
        "AskUserQuestion",
        "Model work runs exclusively through Claude",
        "Use the Agent tool",
    )
    assert all(token not in markdown for token in forbidden)


def test_showoff_skill_keeps_complete_workflow_resources() -> None:
    required = (
        "scripts/project-context.mjs",
        "scripts/validate-output.mjs",
        "templates/showoff-plan.md",
        "templates/composition-brief.md",
        "references/orchestration.md",
        "references/composition.md",
        "references/delivery.md",
        "references/media.md",
        "references/narrative.md",
        "references/project-inspection.md",
        "references/taste.md",
    )
    assert all((SKILL_DIR / relative).is_file() for relative in required)
