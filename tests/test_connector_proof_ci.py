"""Contract tests for the narrowly scoped connector-proof workflow."""

from pathlib import Path
import re
import shlex
import textwrap

import pytest


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "connector-proof.yml"
)


def active_run_steps(yaml_text: str) -> list[str]:
    """Extract only ``jobs.*.steps[*].run`` values and discard heredoc payloads."""
    lines = yaml_text.splitlines()
    steps: list[str] = []
    jobs_indent: int | None = None
    job_indent: int | None = None
    steps_indent: int | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if stripped == "jobs:" and indent == 0:
            jobs_indent = indent
            job_indent = None
            steps_indent = None
            index += 1
            continue
        if jobs_indent is not None and stripped and indent <= jobs_indent:
            jobs_indent = None
            job_indent = None
            steps_indent = None
            index += 1
            continue
        if (
            jobs_indent is not None
            and indent == jobs_indent + 2
            and stripped.endswith(":")
            and stripped != "steps:"
            and not stripped.startswith("-")
        ):
            job_indent = indent
            steps_indent = None
            index += 1
            continue
        if job_indent is not None and stripped and indent <= job_indent:
            job_indent = None
            steps_indent = None
            continue
        if stripped == "steps:" and job_indent is not None and indent == job_indent + 2:
            steps_indent = indent
            index += 1
            continue

        if steps_indent is None:
            index += 1
            continue
        if stripped and indent <= steps_indent:
            steps_indent = None
            continue

        match = re.match(r"^(\s*)(-\s+)?run:\s*(.*?)\s*$", line)
        if not match or line.lstrip().startswith("#"):
            index += 1
            continue

        is_list_item = match.group(2) is not None
        expected_indent = steps_indent + (2 if is_list_item else 4)
        if indent != expected_indent:
            index += 1
            continue

        value = match.group(3)
        if value in {"|", ">", "|-", ">-", "|+", ">+"}:
            block: list[str] = []
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                    break
                if candidate.strip() and not candidate.lstrip().startswith("#"):
                    block.append(candidate.strip())
                index += 1
            steps.append(_without_heredoc_payloads("\n".join(block)))
            continue

        if value and not value.startswith("#"):
            try:
                value = " ".join(shlex.split(value, comments=True))
            except ValueError:
                pass
            steps.append(value)
        index += 1
    return steps


def _without_heredoc_payloads(script: str) -> str:
    """Remove shell heredoc bodies so inert data cannot satisfy command checks."""
    kept: list[str] = []
    delimiters: list[str] = []
    for line in script.splitlines():
        if delimiters:
            if line.strip() == delimiters[0]:
                delimiters.pop(0)
            continue
        kept.append(line)
        delimiters.extend(
            re.findall(r"<<-?['\"]?([A-Za-z0-9_]+)['\"]?", line)
        )
    return "\n".join(kept)


def assert_required_commands(yaml_text: str) -> None:
    commands = "\n".join(active_run_steps(yaml_text))
    required = {
        "connector acceptance": r"(?m)(?:^|[;&|]\s*)python\s+-m\s+pytest\s+tests/test_phoenix_learn\.py(?:\s|$)",
        "trace verification": r"(?m)(?:^|[;&|]\s*)phoenix-mcp\s+verify-trace(?:\s|$)",
    }
    missing = [name for name, pattern in required.items() if not re.search(pattern, commands)]
    assert not missing, f"missing executable command(s): {', '.join(missing)}"


def test_real_workflow_runs_connector_test_and_verifies_trace():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert_required_commands(text)
    commands = "\n".join(active_run_steps(text))
    assert "test -s .phoenix/trace.jsonl" in commands
    assert re.search(r"if\s+phoenix-mcp\s+verify-trace;\s*then", commands)
    assert re.search(
        r"python\s+-m\s+pytest\s+tests/test_phoenix_learn\.py\s+"
        r"tests/test_connector_proof_ci\.py",
        commands,
    )
    active_yaml = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    for path in ("src/**", "Cargo.toml", "Cargo.lock", "tests/test_connector_proof_ci.py"):
        assert f'"{path}"' in active_yaml


def test_comments_alone_do_not_count_as_commands():
    fixture = textwrap.dedent(
        """
        # run: python -m pytest tests/test_phoenix_learn.py
        jobs:
          proof:
            steps:
              - run: |
                  # python -m pytest tests/test_phoenix_learn.py
                  # phoenix-mcp verify-trace
                  echo no-proof
        """
    )
    with pytest.raises(AssertionError, match="connector acceptance.*trace verification"):
        assert_required_commands(fixture)


def test_env_run_and_heredoc_payloads_do_not_count_as_commands():
    fixture = textwrap.dedent(
        """
        jobs:
          proof:
            steps:
              - name: inert data
                env:
                  run: python -m pytest tests/test_phoenix_learn.py
                run: |
                  cat <<'EOF'
                  phoenix-mcp verify-trace
                  EOF
                  echo no-proof
        """
    )
    with pytest.raises(AssertionError, match="connector acceptance.*trace verification"):
        assert_required_commands(fixture)


def test_top_level_steps_do_not_count_as_job_steps():
    fixture = textwrap.dedent(
        """
        steps:
          - run: python -m pytest tests/test_phoenix_learn.py
          - run: phoenix-mcp verify-trace
        """
    )
    with pytest.raises(AssertionError, match="connector acceptance.*trace verification"):
        assert_required_commands(fixture)


def test_numeric_heredoc_payload_does_not_count_as_commands():
    fixture = textwrap.dedent(
        """
        jobs:
          proof:
            steps:
              - run: |
                  cat <<123
                  python -m pytest tests/test_phoenix_learn.py
                  phoenix-mcp verify-trace
                  123
                  echo no-proof
        """
    )
    with pytest.raises(AssertionError, match="connector acceptance.*trace verification"):
        assert_required_commands(fixture)


def test_multiple_heredoc_payloads_do_not_count_as_commands():
    fixture = textwrap.dedent(
        """
        jobs:
          proof:
            steps:
              - run: |
                  cat <<ALPHA <<123
                  harmless
                  ALPHA
                  python -m pytest tests/test_phoenix_learn.py
                  phoenix-mcp verify-trace
                  123
                  echo no-proof
        """
    )
    with pytest.raises(AssertionError, match="connector acceptance.*trace verification"):
        assert_required_commands(fixture)


def test_jobs_steps_without_job_key_do_not_count():
    fixture = textwrap.dedent(
        """
        jobs:
          steps:
            - run: python -m pytest tests/test_phoenix_learn.py
            - run: phoenix-mcp verify-trace
        """
    )
    with pytest.raises(AssertionError, match="connector acceptance.*trace verification"):
        assert_required_commands(fixture)


@pytest.mark.parametrize(
    "only_command, missing",
    [
        ("python -m pytest tests/test_phoenix_learn.py", "trace verification"),
        ("phoenix-mcp verify-trace", "connector acceptance"),
    ],
)
def test_workflow_missing_either_required_command_fails(only_command, missing):
    fixture = f"jobs:\n  proof:\n    steps:\n      - run: {only_command}\n"
    with pytest.raises(AssertionError, match=missing):
        assert_required_commands(fixture)
