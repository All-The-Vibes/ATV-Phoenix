"""Behavioral checks for live Phoenix proof-state isolation."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = ROOT / ".gitignore"
HOOK = ROOT / ".githooks" / "pre-commit"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test Runner")
    git(repo, "config", "user.email", "tests@example.invalid")
    git(repo, "config", "core.hooksPath", ".githooks")
    shutil.copyfile(GITIGNORE, repo / ".gitignore")
    hooks = repo / ".githooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    shutil.copyfile(HOOK, hook)
    hook.chmod(hook.stat().st_mode | 0o111)
    return repo


def write(repo: Path, relative_path: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n", encoding="utf-8")


def is_ignored(repo: Path, relative_path: str) -> bool:
    write(repo, relative_path)
    return git(repo, "check-ignore", "-q", "--", relative_path, check=False).returncode == 0


def test_root_phoenix_rule_is_unique_and_root_scoped(tmp_path: Path) -> None:
    active_rules = [
        line.strip()
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert active_rules.count("/.phoenix/") == 1
    assert ".phoenix/" not in active_rules

    repo = make_repo(tmp_path)
    assert is_ignored(repo, ".phoenix/trace.jsonl")
    assert not is_ignored(repo, "fixtures/.phoenix/trace.jsonl")


@pytest.mark.parametrize(
    "relative_path",
    [
        ".phoenix-ralph/backlog.json",
        ".phoenix-ralph/driver.log",
        ".phoenix-ralph/completed.json",
        ".phoenix-ralph/completed-003.json",
        ".phoenix-ralph/acceptance-contract.json",
    ],
)
def test_mutable_root_ralph_state_is_ignored(
    tmp_path: Path, relative_path: str
) -> None:
    assert is_ignored(make_repo(tmp_path), relative_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        ".phoenix-ralph/PROMPT.md",
        ".phoenix-ralph/done-check.json",
        ".phoenix-ralph/fixtures/completed-example.json",
        "evals/m3-live-copilot/live-trace.jsonl",
    ],
)
def test_intentional_fixtures_remain_allowed(
    tmp_path: Path, relative_path: str
) -> None:
    assert not is_ignored(make_repo(tmp_path), relative_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        ".phoenix/trace.jsonl",
        ".phoenix/nested/state.json",
        ".phoenix-ralph/backlog.json",
        ".phoenix-ralph/driver.log",
        ".phoenix-ralph/completed-003.json",
        ".phoenix-ralph/acceptance-contract.json",
    ],
)
def test_hook_rejects_staged_live_runtime_state(
    tmp_path: Path, relative_path: str
) -> None:
    repo = make_repo(tmp_path)
    write(repo, relative_path)
    git(repo, "add", "-f", "--", relative_path)

    result = git(repo, "commit", "-m", "test fixture", check=False)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "live Phoenix runtime state" in output
    assert relative_path in output


@pytest.mark.parametrize(
    "relative_path",
    [
        ".phoenix-ralph/PROMPT.md",
        ".phoenix-ralph/done-check.json",
        ".phoenix-ralph/fixtures/completed-example.json",
        "evals/m3-live-copilot/live-trace.jsonl",
    ],
)
def test_hook_accepts_prompts_done_checks_and_historical_fixtures(
    tmp_path: Path, relative_path: str
) -> None:
    repo = make_repo(tmp_path)
    write(repo, relative_path)
    git(repo, "add", "--", relative_path)

    result = git(repo, "commit", "-m", "test fixture", check=False)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "skip compile check" in output
