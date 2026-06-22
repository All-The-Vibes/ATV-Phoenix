"""Acceptance check for issue #4 — Scout adapter: finish dist/scout MCP wiring.

Verifies that dist/scout/install.ps1:
  - exists (it did not before this beat)
  - contains the key Scout-specific install operations
  - references the phoenix-self-heal skill correctly

Also verifies the existing phoenix-self-heal.skill.md has valid frontmatter,
and that the phoenix-mcp binary produces a valid smoke sense result.

Tests are deterministic and offline (no real install performed).
Done-check: pytest tests/test_scout_install.py exits 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_SCOUT = ROOT / "dist" / "scout"
INSTALL_PS1 = DIST_SCOUT / "install.ps1"
SKILL_MD = DIST_SCOUT / "phoenix-self-heal.skill.md"
BINARY = ROOT / "target" / "release" / "phoenix-mcp.exe"


def test_install_script_exists() -> None:
    """dist/scout/install.ps1 must exist — it is the Scout adapter installer."""
    assert INSTALL_PS1.exists(), (
        f"dist/scout/install.ps1 not found at {INSTALL_PS1}. "
        "The Scout adapter is incomplete without an install script."
    )


def test_install_script_copies_self_heal_skill() -> None:
    """Installer must copy the phoenix-self-heal skill to ~/.copilot/skills/."""
    content = INSTALL_PS1.read_text(encoding="utf-8")
    assert "phoenix-self-heal" in content, (
        "install.ps1 must reference phoenix-self-heal to install the Scout skill"
    )
    assert ".copilot" in content and "skills" in content, (
        "install.ps1 must target the ~/.copilot/skills/ directory"
    )


def test_install_script_references_binary() -> None:
    """Installer must verify the phoenix-mcp binary is accessible."""
    content = INSTALL_PS1.read_text(encoding="utf-8")
    assert "phoenix-mcp" in content, (
        "install.ps1 must reference the phoenix-mcp binary"
    )


def test_self_heal_skill_has_valid_frontmatter() -> None:
    """phoenix-self-heal.skill.md must have name + description in YAML frontmatter."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---"), "skill file must start with YAML frontmatter"
    assert "name: phoenix-self-heal" in text, "frontmatter must include name"
    assert "description:" in text, "frontmatter must include description"


def test_binary_smoke_sense_exits_zero() -> None:
    """phoenix-mcp binary must return valid JSON for a trivially-passing sense check."""
    if not BINARY.exists():
        import pytest
        pytest.skip(f"binary not found at {BINARY} — build first")

    check = json.dumps({
        "kind": "command_exit",
        "target": ["python", "--version"],
        "expect": 0,
    })
    tmp = Path(__file__).parent / "_smoke_check.json"
    try:
        tmp.write_text(check, encoding="utf-8")
        result = subprocess.run(
            [str(BINARY), "sense", f"@{tmp}"],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        assert data.get("ok") is True, f"smoke sense must return ok=true, got: {data}"
    finally:
        tmp.unlink(missing_ok=True)
