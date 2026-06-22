"""Acceptance check for issue #8 — Windows PS5.1 / cmd-shim fix in phoenix-ralph.ps1.

Verifies that dist/ralph/phoenix-ralph.ps1:
  1. Has a PS version guard that self-promotes to pwsh on PS < 6
  2. Sets $PSNativeCommandArgumentPassing = 'Standard' for PS 7+
  3. Fails fast (exits nonzero) on repeated launch failures instead of silently
     burning NoProgressStop iterations
  4. The no-progress guard accounts for a spawn failure (nonzero exit + unchanged trace)

Tests are static (parse the script text; no shell spawning needed).
Done-check: pytest tests/test_ralph_ps_guard.py exits 0.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RALPH = ROOT / "dist" / "ralph" / "phoenix-ralph.ps1"


def _script() -> str:
    return RALPH.read_text(encoding="utf-8", errors="replace")


def test_ralph_exists() -> None:
    assert RALPH.exists(), f"phoenix-ralph.ps1 not found at {RALPH}"


def test_ps_version_self_promotion() -> None:
    """Script must self-promote to pwsh when running under PS < 6 (PS 5.1 fix)."""
    text = _script()
    assert "PSVersion" in text and ("Major" in text or "Version.Major" in text), (
        "Script must check PSVersionTable.PSVersion.Major"
    )
    assert "pwsh" in text, (
        "Script must invoke 'pwsh' to self-promote away from PS 5.1"
    )
    # Must re-exec itself, not just a sub-command
    assert "PSCommandPath" in text or "-File" in text, (
        "Self-promotion must pass -File $PSCommandPath (re-exec this script under pwsh)"
    )


def test_standard_arg_passing() -> None:
    """Script must set $PSNativeCommandArgumentPassing = 'Standard' for PS 7+ belt-and-suspenders."""
    text = _script()
    assert "PSNativeCommandArgumentPassing" in text, (
        "Script must set $PSNativeCommandArgumentPassing = 'Standard' to pin PS7 arg handling"
    )
    assert "Standard" in text, (
        "$PSNativeCommandArgumentPassing must be set to 'Standard'"
    )


def test_spawn_failure_is_fatal_not_warn() -> None:
    """A spawn failure (agent exits nonzero + trace/backlog unchanged) must be fatal, not just a warning."""
    text = _script()
    # The old code only Warn'd on nonzero exit. New code must treat launch failure as fatal
    # when the trace signature is unchanged (no progress AND nonzero exit = never launched).
    # We check that the fix is present: Die or explicit exit on spawn failure when no progress.
    assert (
        'Die "agent' in text
        or 'Die "copilot' in text
        or "launch fail" in text.lower()
        or "spawn fail" in text.lower()
        or ("LASTEXITCODE -ne 0" in text and "noProgress" in text and "Die" in text)
    ), (
        "A spawn failure (nonzero exit + no trace change) must call Die, not just Warn. "
        "Silent iteration-burning is the bug."
    )


def test_no_inline_prompt_arg() -> None:
    """The prompt must NOT be passed inline as a -p CLI argument (the mangling vector).
    It should be written to a temp file or passed via stdin/file mechanism."""
    text = _script()
    # Old code: $flat = ... ; & $Copilot -p $flat
    # Check that the inline $flat -p pattern is gone
    import re
    # Look for the old pattern: -p followed by a variable (not a @file)
    old_pattern = re.compile(r'\$Copilot\s+-p\s+\$flat', re.IGNORECASE)
    assert not old_pattern.search(text), (
        "Old inline -p $flat pattern still present — this is the quote-mangling vector. "
        "Pass the prompt via a temp file (@file) or stdin instead."
    )