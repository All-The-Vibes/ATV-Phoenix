"""The Python half of this repository must be installable by pip.

Before `pyproject.toml` existed, `pip install git+https://github.com/All-The-Vibes/ATV-Phoenix`
failed with "neither 'setup.py' nor 'pyproject.toml' found". A downstream consumer of
`phoenix_learn` had to either add an absolute `sys.path` entry, which is machine-specific
and breaks in CI, or vendor the whole repository as a submodule, which drags ~300 upstream
tests into the consumer's collection root.

Each check below compares two independent sources, so none of them can be satisfied by
editing an assertion:

- `pyproject.toml` declares what ships; the filesystem says what exists.
- `Cargo.toml` owns the version; `pyproject.toml` has to agree with it.
- The wheel is built by setuptools, not by this file.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
CARGO = REPO / "Cargo.toml"


def _pyproject() -> dict:
    assert PYPROJECT.is_file(), f"no pyproject.toml at {PYPROJECT}"
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _declared_packages() -> set[str]:
    data = _pyproject()
    packages = data.get("tool", {}).get("setuptools", {}).get("packages")
    assert packages, "pyproject.toml declares no [tool.setuptools] packages"
    return set(packages)


def _packages_on_disk() -> set[str]:
    return {
        d.name
        for d in REPO.iterdir()
        if d.is_dir() and not d.name.startswith(".") and (d / "__init__.py").is_file()
    }


def _cargo_version() -> str:
    text = CARGO.read_text(encoding="utf-8")
    package = text.split("[package]", 1)[1]
    for line in package.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            break
        if stripped.startswith("version"):
            return stripped.split("=", 1)[1].strip().strip('"')
    raise AssertionError("no version field in the [package] section of Cargo.toml")


def test_pyproject_declares_every_importable_package():
    """Adding a root package without declaring it means it never reaches the wheel."""
    declared = _declared_packages()
    on_disk = _packages_on_disk()
    assert declared == on_disk, (
        f"pyproject.toml declares {sorted(declared)} but the repository root holds "
        f"{sorted(on_disk)}. Undeclared packages are silently left out of the wheel."
    )


def test_declared_packages_exist():
    for name in sorted(_declared_packages()):
        assert (REPO / name / "__init__.py").is_file(), (
            f"pyproject.toml declares {name} but {name}/__init__.py is missing"
        )


def test_python_version_matches_cargo():
    """Two version sources drift unless something compares them."""
    declared = _pyproject()["project"]["version"]
    assert declared == _cargo_version(), (
        f"pyproject.toml is {declared} and Cargo.toml is {_cargo_version()}"
    )


def test_wheel_contains_every_declared_package(tmp_path):
    """setuptools, not this file, decides what ends up in the artifact."""
    try:
        import setuptools  # noqa: F401
    except ImportError:
        import pytest

        pytest.skip("setuptools is absent, so an isolation-free build cannot run here")

    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "-q", "-w", str(tmp_path), str(REPO)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, f"pip wheel failed:\n{build.stdout}\n{build.stderr}"

    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {[w.name for w in wheels]}"

    with zipfile.ZipFile(wheels[0]) as archive:
        shipped = {name.split("/")[0] for name in archive.namelist()}
    missing = _declared_packages() - shipped
    assert not missing, f"declared but absent from the wheel: {sorted(missing)}"
