"""
tests/test_live_gate_windows.py

Static acceptance tests for issue #12 — live/serve gate gotchas on Windows.
Verifies the template (dist/ralph/live-gate-template.mjs) and README bake in:
  FIX 1: stdio:'ignore' + port-kill teardown (no stdio:'inherit' for serve)
  FIX 2: case-insensitive innerText matching
"""
import pathlib
import re

REPO = pathlib.Path(__file__).parent.parent
TEMPLATE = REPO / "dist" / "ralph" / "live-gate-template.mjs"
README   = REPO / "dist" / "ralph" / "README.md"


def test_template_exists():
    """The live-gate template file must exist."""
    assert TEMPLATE.exists(), f"live-gate-template.mjs not found at {TEMPLATE}"


def test_template_uses_stdio_ignore():
    """Template must spawn serve with stdio:'ignore', never stdio:'inherit'."""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "stdio: 'ignore'" in src or 'stdio:"ignore"' in src, (
        "Template must use stdio:'ignore' for the serve spawn (FIX 1 — prevents "
        "~14min hang when detached grandchildren hold the inherited pipe on Windows)"
    )
    assert "stdio: 'inherit'" not in src and 'stdio:"inherit"' not in src, (
        "Template must NOT use stdio:'inherit' for serve — causes sense hang on Windows"
    )


def test_template_kills_by_port():
    """Template teardown must kill by port (netstat/taskkill), not just by pid."""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "netstat" in src, (
        "Template teardown must use netstat to find and kill the process holding "
        "the serve port — pid-tree kill alone misses detached grandchildren (FIX 1)"
    )
    assert "taskkill" in src or "kill" in src.lower(), (
        "Template teardown must kill processes found via netstat/port scan"
    )


def test_template_case_insensitive_match():
    """Template must compare innerText case-insensitively (toLowerCase)."""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "toLowerCase" in src, (
        "Template must use toLowerCase() for marker matching — innerText applies "
        "CSS text-transform, so uppercase headings cause false-RED (FIX 2)"
    )


def test_readme_documents_live_gate_rules():
    """README must document both live-gate gotchas for issue #12."""
    text = README.read_text(encoding="utf-8")
    assert "stdio:'inherit'" in text or "stdio: 'inherit'" in text, (
        "README must warn against stdio:'inherit' for serve processes"
    )
    assert "toLowerCase" in text or "case-insensitive" in text.lower(), (
        "README must document case-insensitive innerText matching rule"
    )
    assert "netstat" in text or "port" in text.lower(), (
        "README must document port-kill teardown strategy"
    )