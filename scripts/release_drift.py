#!/usr/bin/env python3
"""scripts/release_drift.py -- objective release-hygiene check.

Answers one question: has anything shipped since the current version was cut that
nobody wrote down?

The failure this exists to stop happened between 2026-06-21 and 2026-08-01. Ninety-four
commits landed on main, forty-seven of them features, while Cargo.toml stayed at 0.4.0
and CHANGELOG.md's [Unreleased] section documented two of them. Every individual commit
was gated. Nothing was watching the release metadata as a whole.

The rule:

    if commits landed since the version bump, [Unreleased] must document something.

Deliberately anchored to the commit that last changed the version line in Cargo.toml,
not to a git tag. Tags are often absent from a fresh or shallow clone, and anchoring to
one would turn this red for everybody in the window between merging a release and
pushing its tag.

Exit codes:
    0  no drift, or the answer cannot be established (see below)
    1  drift proven: commits landed since the bump and [Unreleased] is empty
    2  the changelog or manifest could not be read at all

Unknown is reported as exit 0 with an explicit UNKNOWN line. When git is missing, the
clone is shallow, or the bump commit is not in history, this check cannot see the truth,
and a red it cannot justify would be a lie. It says so instead.

Run with --json for machine-readable output.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CARGO = REPO / "Cargo.toml"
CHANGELOG = REPO / "CHANGELOG.md"


def _read(path):
    return path.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8")


def cargo_version():
    package = _read(CARGO).split("[[bin]]")[0]
    m = re.search(r'^version\s*=\s*"([^"]+)"', package, re.M)
    return m.group(1) if m else None


def unreleased_entry_count():
    """Content lines under '## [Unreleased]', up to the next '## ' heading.

    A line counts when it is a list item or a '### ' subsection. Prose such as the
    placeholder 'Nothing yet.' does not count, so an empty section stays empty.
    """
    text = _read(CHANGELOG)
    m = re.search(r"^## \[Unreleased\]\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    section = rest[: nxt.start()] if nxt else rest
    return sum(
        1 for line in section.splitlines()
        if line.startswith("- ") or line.startswith("* ") or line.startswith("### ")
    )


def _scrubbed_env():
    """Environment with every GIT_* variable removed.

    Git hooks export GIT_DIR and GIT_WORK_TREE. Inheriting them makes `git -C <path>`
    operate on the hook's repository no matter which path is passed, so a directory that
    is not a repository at all would silently answer for the real one. The pre-push hook
    caught exactly that in this script.
    """
    import os
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(*args):
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO)] + list(args),
            capture_output=True, text=True, timeout=30, env=_scrubbed_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def commits_since_version_bump(version):
    """Commits on HEAD since the commit that introduced this version in Cargo.toml.

    Returns None when git cannot answer, which includes a shallow clone and a
    version line that is not in the fetched history.
    """
    if _git("rev-parse", "--git-dir") is None:
        return None
    bump = _git("log", "-1", "--format=%H", "-S", 'version = "%s"' % version, "--", "Cargo.toml")
    if not bump:
        return None
    count = _git("rev-list", "--count", "%s..HEAD" % bump)
    if count is None:
        return None
    try:
        return int(count)
    except ValueError:
        return None


def evaluate():
    if not CARGO.exists() or not CHANGELOG.exists():
        return {"status": "error", "reason": "Cargo.toml or CHANGELOG.md is missing"}
    version = cargo_version()
    if version is None:
        return {"status": "error", "reason": "no version field in the [package] section"}
    entries = unreleased_entry_count()
    if entries is None:
        return {"status": "error", "reason": "CHANGELOG.md has no '## [Unreleased]' heading"}
    commits = commits_since_version_bump(version)
    result = {"version": version, "unreleased_entries": entries, "commits_since_bump": commits}
    if commits is None:
        result["status"] = "unknown"
        result["reason"] = (
            "git could not report commits since the %s bump (no git, shallow clone, or the "
            "bump commit is outside the fetched history)" % version
        )
    elif commits > 0 and entries == 0:
        result["status"] = "drift"
        result["reason"] = (
            "%d commit(s) landed since %s was cut and [Unreleased] documents none of them. "
            "Add the entry in the PR that ships the change, or cut the next release."
            % (commits, version)
        )
    else:
        result["status"] = "ok"
        result["reason"] = (
            "%d commit(s) since %s, %d [Unreleased] entr(ies)" % (commits, version, entries)
        )
    return result


def main():
    p = argparse.ArgumentParser(description="Report release-metadata drift.")
    p.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = p.parse_args()
    result = evaluate()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("release-drift: %s -- %s" % (result["status"].upper(), result["reason"]))
    return {"ok": 0, "unknown": 0, "drift": 1, "error": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
