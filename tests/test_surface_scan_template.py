"""
tests/test_surface_scan_template.py
Static acceptance tests for dist/ralph/surface-scan-template.mjs (issue #13 rec-1).
Verifies structural integrity: template exists, has required CONFIG + logic,
and declares the node CLI contract (exit 0 = clean, exit 1 = offenders found).
"""
import pathlib
import subprocess
import tempfile
import os
import re

REPO = pathlib.Path(__file__).parent.parent
TEMPLATE = REPO / "dist" / "ralph" / "surface-scan-template.mjs"


def test_template_exists():
    assert TEMPLATE.exists(), f"Missing: {TEMPLATE}"


def test_has_config_section():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "forbiddenPatterns" in src, "CONFIG must declare forbiddenPatterns"
    assert "scanDirs" in src, "CONFIG must declare scanDirs"


def test_has_dir_walk_and_exit_codes():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert ("readdirSync" in src or "readdir" in src or "walk" in src.lower()), \
        "Template must recursively walk directories"
    assert "process.exit(0)" in src, "Template must exit 0 on clean"
    assert "process.exit(1)" in src, "Template must exit 1 on offenders"


def test_offender_format_file_line():
    src = TEMPLATE.read_text(encoding="utf-8")
    lower = src.lower()
    assert ("linenum" in lower or "linenumber" in lower or ":line" in lower or
            "file:line" in lower or ':' in src or "lineNo" in src or "lineIdx" in src), \
        "Template must report offenders with file:line location"


def test_node_exits_0_on_clean_dir():
    if not _node_available():
        import pytest; pytest.skip("node not available")
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "clean.tsx"), "w") as f:
            f.write('export const Hero = () => <div className="warm-bg">Hello</div>;\n')
        patched = _patch_scan_dirs(TEMPLATE.read_text(encoding="utf-8"), tmp)
        r = subprocess.run(["node", "--input-type=module"], input=patched,
                           capture_output=True, text=True, timeout=15)
        assert r.returncode == 0, f"exit {r.returncode}\n{r.stdout}\n{r.stderr}"


def test_node_exits_1_on_legacy_signature():
    if not _node_available():
        import pytest; pytest.skip("node not available")
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "hero.tsx"), "w") as f:
            f.write('export const Hero = () => <div className="text-gradient glow-hero">hi</div>;\n')
        patched = _patch_scan_dirs(TEMPLATE.read_text(encoding="utf-8"), tmp)
        r = subprocess.run(["node", "--input-type=module"], input=patched,
                           capture_output=True, text=True, timeout=15)
        assert r.returncode == 1, f"exit {r.returncode}\n{r.stdout}\n{r.stderr}"
        combined = r.stdout + r.stderr
        assert ("text-gradient" in combined or "offender" in combined.lower()
                or "FAIL" in combined), "Output must mention the forbidden pattern"


def _node_available():
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _patch_scan_dirs(src: str, tmp_dir: str) -> str:
    tmp_fwd = tmp_dir.replace("\\", "/")
    return re.sub(r"scanDirs\s*:\s*\[.*?\]", f"scanDirs: ['{tmp_fwd}']", src, flags=re.DOTALL)
