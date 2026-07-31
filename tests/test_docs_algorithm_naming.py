from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCLAIMER_PATTERNS = ("without GEPA's", "in the spirit of GEPA")


def _assert_no_unqualified_gepa(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if "GEPA" not in line:
            continue
        if any(pattern in line for pattern in DISCLAIMER_PATTERNS):
            continue
        previous = lines[idx - 2] if idx > 1 else ""
        next_line = lines[idx] if idx < len(lines) else ""
        window = " ".join((previous, line, next_line))
        assert any(pattern in window for pattern in DISCLAIMER_PATTERNS), (
            f"Unqualified GEPA attribution in {path}:{idx}: {line!r}"
        )


def test_no_unqualified_gepa_claim():
    _assert_no_unqualified_gepa(ROOT / "AGENTS.md")
    for path in (ROOT / "phoenix_learn").rglob("*.py"):
        _assert_no_unqualified_gepa(path)
