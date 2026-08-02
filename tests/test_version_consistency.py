"""
tests/test_version_consistency.py

Guards the release metadata that drifted before 0.5.0: Cargo.toml said 0.4.0 while
94 commits had landed on main since the v0.4.0 tag, the CHANGELOG had no link
reference definitions at all, and the release headings used an em dash instead of
the Keep a Changelog date separator.

Four invariants, all checkable offline:
  1. README.md's version badge matches Cargo.toml.
  2. The newest release heading in CHANGELOG.md matches Cargo.toml.
  3. Every release heading uses "## [X.Y.Z] - YYYY-MM-DD".
  4. Every release heading, and Unreleased, has a link reference definition.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).parent.parent
CARGO = REPO / "Cargo.toml"
README = REPO / "README.md"
CHANGELOG = REPO / "CHANGELOG.md"

# "## [1.2.3] - 2026-08-01". The separator is a plain hyphen, per Keep a Changelog.
RELEASE_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})\s*$", re.M)
# Any "## [...]" heading, so a malformed one is seen rather than silently skipped.
ANY_HEADING = re.compile(r"^## \[([^\]]+)\](.*)$", re.M)
LINK_DEF = re.compile(r"^\[([^\]]+)\]:\s*(\S+)\s*$", re.M)


def _read(path):
    return path.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8")


def cargo_version():
    text = _read(CARGO)
    package = text.split("[[bin]]")[0]
    m = re.search(r'^version\s*=\s*"([^"]+)"', package, re.M)
    assert m, "no version field in the [package] section of Cargo.toml"
    return m.group(1)


def test_readme_badge_matches_cargo_version():
    version = cargo_version()
    text = _read(README)
    assert ("version-%s-" % version) in text, (
        "README.md version badge does not match Cargo.toml version %s. "
        "Bump the shields.io badge URL in the same commit as the Cargo bump." % version
    )
    assert ("Version %s" % version) in text, (
        "README.md badge alt text does not match Cargo.toml version %s" % version
    )


def test_changelog_documents_the_cargo_version_first():
    version = cargo_version()
    releases = RELEASE_HEADING.findall(_read(CHANGELOG))
    assert releases, "CHANGELOG.md has no release heading in '## [X.Y.Z] - YYYY-MM-DD' form"
    newest = releases[0][0]
    assert newest == version, (
        "CHANGELOG.md's newest release is %s but Cargo.toml is %s. Cut the release "
        "section in the same commit as the version bump." % (newest, version)
    )


def test_every_release_heading_uses_the_keep_a_changelog_form():
    text = _read(CHANGELOG)
    bad = []
    for name, rest in ANY_HEADING.findall(text):
        if name == "Unreleased":
            continue
        line = "## [%s]%s" % (name, rest)
        if not RELEASE_HEADING.match(line):
            bad.append(line.strip())
    assert not bad, (
        "These CHANGELOG headings are not '## [X.Y.Z] - YYYY-MM-DD' (a plain hyphen, "
        "not an em dash): %r" % bad
    )


def test_every_version_has_a_link_reference_definition():
    text = _read(CHANGELOG)
    defined = {name for name, _ in LINK_DEF.findall(text)}
    expected = {name for name, _ in ANY_HEADING.findall(text)}
    assert expected, "CHANGELOG.md has no '## [...]' headings at all"
    missing = sorted(expected - defined)
    assert not missing, (
        "These CHANGELOG sections have no link reference definition at the bottom of "
        "the file: %r. Keep a Changelog expects a compare link per version." % missing
    )
