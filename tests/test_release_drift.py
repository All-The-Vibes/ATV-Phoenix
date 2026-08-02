"""
tests/test_release_drift.py

Two things are under test here, and the second one is the point.

First, scripts/release_drift.py actually detects the failure it exists for: commits
landing after a version was cut while [Unreleased] documents none of them. Tested against
throwaway git repositories built under tmp_path, never against this checkout.

Second, and this is what was missing before: the release checks are WIRED INTO THE GATE.
A guard nothing runs is not enforcement. tests/test_version_consistency.py shipped in the
0.5.0 release commit and scripts/ci-local.sh did not invoke it, so it would have sat green
and unread forever. These tests assert both ci-local entry points call both checks.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "release_drift.py"
CI_SH = REPO / "scripts" / "ci-local.sh"
CI_PS1 = REPO / "scripts" / "ci-local.ps1"

CARGO = '[package]\nname = "phoenix"\nversion = "%s"\nedition = "2021"\n'
CHANGELOG_EMPTY = "# Changelog\n\n## [Unreleased]\n\nNothing yet.\n\n## [0.5.0] - 2026-08-01\n\n- shipped\n"
CHANGELOG_FULL = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- a new thing (#1)\n\n## [0.5.0] - 2026-08-01\n\n- shipped\n"


def _read(path):
    return path.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8")


def _clean_env(extra=None):
    """os.environ with every GIT_* variable removed.

    Load-bearing. These tests build throwaway git repositories, and pytest runs inside
    the pre-push hook, which exports GIT_DIR and GIT_WORK_TREE. Without this, `git init`
    and `git commit` in a temp directory operate on the HOOK'S repository instead: an
    earlier version of this file committed its own fixtures ("feat: thing 0", "initial at
    0.4.0") onto the branch under test and had to be recovered from the reflog.
    """
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if extra:
        env.update(extra)
    return env


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@example.com", "-c", "user.name=t"] + list(args),
        cwd=str(cwd), capture_output=True, text=True, timeout=60, env=_clean_env(),
    )


def _fake_repo(root, changelog, extra_commits=0):
    """A minimal git repo holding the script, a Cargo.toml, and a CHANGELOG."""
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "release_drift.py")
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (root / "Cargo.toml").write_text(CARGO % "0.4.0", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial at 0.4.0")
    # The bump commit the script anchors to.
    (root / "Cargo.toml").write_text(CARGO % "0.5.0", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "chore(release): cut 0.5.0")
    for i in range(extra_commits):
        (root / ("shipped_%d.txt" % i)).write_text("work\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "feat: thing %d" % i)
    return root


def _run(root, env=None):
    merged = _clean_env(env)
    r = subprocess.run(
        ["python", str(root / "scripts" / "release_drift.py"), "--json"],
        capture_output=True, text=True, timeout=60, cwd=str(root), env=merged,
    )
    payload = json.loads(r.stdout) if r.stdout.strip() else {}
    return r.returncode, payload


def _git_available():
    try:
        return subprocess.run(["git", "--version"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def test_drift_is_detected_when_commits_land_with_an_empty_unreleased(tmp_path):
    """The exact 0.4.0 failure, in miniature: work shipped, nobody wrote it down."""
    if not _git_available():
        pytest.skip("git not available")
    root = _fake_repo(tmp_path / "drift", CHANGELOG_EMPTY, extra_commits=3)
    code, payload = _run(root)
    assert payload.get("status") == "drift", payload
    assert payload.get("commits_since_bump") == 3, payload
    assert payload.get("unreleased_entries") == 0, payload
    assert code == 1, "proven drift must exit 1, got %d (%r)" % (code, payload)


def test_no_drift_when_the_unreleased_section_documents_the_work(tmp_path):
    if not _git_available():
        pytest.skip("git not available")
    root = _fake_repo(tmp_path / "documented", CHANGELOG_FULL, extra_commits=3)
    code, payload = _run(root)
    assert payload.get("status") == "ok", payload
    assert payload.get("unreleased_entries") >= 1, payload
    assert code == 0


def test_no_drift_immediately_after_a_release_is_cut(tmp_path):
    """Zero commits since the bump is the clean state, even with an empty section.

    This is why the check anchors to the version-bump commit rather than a tag: the
    window between merging a release and pushing its tag must not be red.
    """
    if not _git_available():
        pytest.skip("git not available")
    root = _fake_repo(tmp_path / "justcut", CHANGELOG_EMPTY, extra_commits=0)
    code, payload = _run(root)
    assert payload.get("status") == "ok", payload
    assert payload.get("commits_since_bump") == 0, payload
    assert code == 0


def test_unknown_is_reported_rather_than_a_red_it_cannot_justify(tmp_path):
    """No git repository means the question cannot be answered. Say so, do not fail."""
    root = tmp_path / "nogit"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "release_drift.py")
    (root / "CHANGELOG.md").write_text(CHANGELOG_EMPTY, encoding="utf-8")
    (root / "Cargo.toml").write_text(CARGO % "0.5.0", encoding="utf-8")
    code, payload = _run(root)
    assert payload.get("status") == "unknown", payload
    assert code == 0, "an unanswerable check must not manufacture a failure"


def test_an_inherited_git_dir_does_not_answer_for_a_different_repository(tmp_path):
    """Regression: git hooks export GIT_DIR, and this script runs inside one.

    With GIT_DIR inherited, `git -C <path>` ignores the path and operates on the hook's
    repository, so a directory that is no repository at all reported a real commit count
    from the wrong tree. The pre-push hook caught this in the first version of this file.
    """
    root = tmp_path / "inherited"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "release_drift.py")
    (root / "CHANGELOG.md").write_text(CHANGELOG_EMPTY, encoding="utf-8")
    (root / "Cargo.toml").write_text(CARGO % "0.5.0", encoding="utf-8")
    code, payload = _run(root, env={"GIT_DIR": str(REPO / ".git"), "GIT_WORK_TREE": str(REPO)})
    assert payload.get("status") == "unknown", (
        "an inherited GIT_DIR leaked another repository into the answer: %r" % payload
    )
    assert code == 0


def test_fixture_repos_cannot_commit_into_an_inherited_repository(tmp_path):
    """Regression for the corruption this file caused, not for the script under test.

    With GIT_DIR pointing at another repository, building a fixture must leave that
    repository's HEAD exactly where it was.
    """
    if not _git_available():
        pytest.skip("git not available")
    bystander = tmp_path / "bystander"
    bystander.mkdir()
    (bystander / "f.txt").write_text("x\n", encoding="utf-8")
    _git(bystander, "init", "-q")
    _git(bystander, "add", "-A")
    _git(bystander, "commit", "-q", "-m", "only commit")
    before = _git(bystander, "rev-parse", "HEAD").stdout.strip()
    assert before, "fixture bystander repo was not created"
    # An uncommitted change, which is what a real worktree mid-change looks like. Without
    # it there is nothing for a leaked `git add -A` to commit and the reproduction is empty.
    (bystander / "work_in_progress.txt").write_text("uncommitted\n", encoding="utf-8")

    import os
    saved = {k: os.environ.get(k) for k in ("GIT_DIR", "GIT_WORK_TREE")}
    os.environ["GIT_DIR"] = str(bystander / ".git")
    os.environ["GIT_WORK_TREE"] = str(bystander)
    try:
        _fake_repo(tmp_path / "isolated", CHANGELOG_EMPTY, extra_commits=2)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    after = _git(bystander, "rev-parse", "HEAD").stdout.strip()
    assert after == before, (
        "building a fixture moved an unrelated repository's HEAD from %s to %s" % (before, after)
    )


def test_release_checks_are_wired_into_both_ci_local_entry_points():
    """The enforcement assertion. A guard the gate never invokes is not a guard."""
    for path in (CI_SH, CI_PS1):
        text = _read(path)
        assert "release_drift.py" in text, (
            "%s does not invoke scripts/release_drift.py, so release drift is not gated"
            % path.name
        )
        assert "test_version_consistency.py" in text, (
            "%s does not invoke tests/test_version_consistency.py, so the version, badge, "
            "and changelog can disagree without the gate noticing" % path.name
        )


def test_the_two_ci_local_entry_points_run_the_same_checks():
    """ci-local.ps1 claims identical checks to ci-local.sh. Hold it to that.

    Compared on the pytest targets and validator scripts each file names, because the
    two are written in different languages and cannot be diffed line for line.
    """
    import re
    token = re.compile(r"(tests/[\w./*-]+\.py|tests/okf|scripts/[\w.-]+\.py|skills/[\w./-]+\.py)")

    def targets(text):
        # Globs appear only in the human-readable stage banners, never in an invocation.
        return {t for t in token.findall(text) if "*" not in t}

    sh = targets(_read(CI_SH))
    ps1 = targets(_read(CI_PS1))
    assert sh == ps1, (
        "ci-local.sh and ci-local.ps1 gate different things. Only in .sh: %r. Only in "
        ".ps1: %r." % (sorted(sh - ps1), sorted(ps1 - sh))
    )
