"""tests/test_real_agent.py -- acceptance gate for scripts/real_agent.py (issue #50).

Failure-first gate for the north-star real repo-aware agent. Proves the property
the naive context-free agent lacked: generated patches apply cleanly *by
construction*. Specifically:
  - the Phoenix arm verify-heals a non-applying patch until `git apply --check` is green;
  - the vanilla arm is a single-shot control (emits the first attempt as-is, no heal);
  - diff extraction survives ```diff fenced model output.

Deterministic and offline: a temp git repo fixture + an injected mock LLM. No
Azure OpenAI, no network, no phoenix binary required.
"""
import re
import subprocess
import sys
import pathlib

import pytest

REPO = pathlib.Path(__file__).parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Hard import (NOT importorskip): missing scripts/real_agent.py must make this
# suite RED so the failure-first phoenix trace is honest.
import real_agent  # noqa: E402


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    _git(["init", "-q"], d)
    _git(["config", "user.email", "t@t"], d)
    _git(["config", "user.name", "t"], d)
    _git(["config", "core.autocrlf", "false"], d)
    (d / "calc.py").write_text("def add(a, b):\n    return a - b\n")  # bug: minus
    _git(["add", "."], d)
    _git(["commit", "-q", "-m", "init"], d)
    return d


def _good_diff(repo):
    """A patch that applies cleanly to the (buggy) repo: fix -> capture -> restore."""
    f = repo / "calc.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    diff = _git(["diff"], repo).stdout
    _git(["checkout", "--", "calc.py"], repo)
    assert "diff --git" in diff and re.search(r"@@ -\d+,\d+ \+\d+,\d+ @@", diff)
    return diff


def _bad_diff(good):
    """Corrupt the removed-line content so it no longer matches the file.

    NB: mangling only the ``@@`` hunk header is not enough -- git apply relocates
    hunks by context matching (the line numbers are hints), so it would still
    apply. Breaking the removed line's text makes ``git apply --check`` fail.
    """
    return good.replace("return a - b", "return a - b_DOES_NOT_MATCH", 1)


class MockLLM:
    """Deterministic LLM stub: pops queued responses, repeats the last one."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, messages):
        self.calls += 1
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def test_apply_check_true_for_applying_patch(repo):
    ok, err = real_agent.apply_check(str(repo), _good_diff(repo))
    assert ok, err


def test_apply_check_false_for_broken_patch(repo):
    ok, _ = real_agent.apply_check(str(repo), _bad_diff(_good_diff(repo)))
    assert not ok


def test_extract_diff_strips_fences(repo):
    good = _good_diff(repo)
    fenced = "Here is the fix:\n```diff\n" + good + "```\n"
    out = real_agent.extract_diff(fenced)
    ok, err = real_agent.apply_check(str(repo), out)
    assert ok, f"extracted diff must apply; err={err}"


def test_phoenix_arm_applies_by_construction(repo):
    good = _good_diff(repo)
    bad = _bad_diff(good)
    llm = MockLLM([bad, good])  # first attempt broken -> must heal to the good one
    inst = {"instance_id": "x", "repo": "o/r", "problem_statement": "fix add"}
    patch = real_agent.solve(inst, str(repo), llm, arm="phoenix", max_heals=3)
    ok, err = real_agent.apply_check(str(repo), patch)
    assert ok, f"phoenix arm must emit an applying patch; err={err}"
    assert llm.calls >= 2, "phoenix arm must have healed at least once"


def test_vanilla_arm_is_single_shot_control(repo):
    good = _good_diff(repo)
    bad = _bad_diff(good)
    llm = MockLLM([bad, good])
    inst = {"instance_id": "x", "repo": "o/r", "problem_statement": "fix add"}
    patch = real_agent.solve(inst, str(repo), llm, arm="vanilla", max_heals=3)
    assert llm.calls == 1, "vanilla control must not run the heal loop"
    ok, _ = real_agent.apply_check(str(repo), patch)
    assert not ok, "vanilla control emits the first (broken) attempt as-is"


def test_run_returns_swebench_shape(repo):
    good = _good_diff(repo)
    llm = MockLLM([good])
    inst = {"instance_id": "proj-1", "repo": "o/r", "base_commit": "HEAD",
            "problem_statement": "fix add"}
    preds = real_agent.run([inst], llm, resolve_repo=lambda i: str(repo), arm="phoenix")
    assert len(preds) == 1
    p = preds[0]
    assert p["instance_id"] == "proj-1"
    assert p["model_patch"].strip()
    assert p["model_name_or_path"] == "gpt-5.1-phoenix"
