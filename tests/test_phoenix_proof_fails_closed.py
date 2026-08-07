"""phoenix-proof must fail when it has nothing to prove.

`.github/workflows/phoenix-proof.yml` gates every proof step on
`steps.acceptance_contract.outputs.declared == 'true'`. On a pull request that is true only when
`.phoenix-ralph/done-check.json` exists on the head. When the file is absent all four proof steps
skip and the job still concludes SUCCESS, so a merge gate reading `statusCheckRollup` treats a run
that proved nothing as Tier 2 satisfied. Six pull requests merged on 2026-08-07 under exactly that
condition, and every one of them reported `phoenix-proof COMPLETED SUCCESS` with the proof steps
skipped.

This asserts the workflow fails closed instead. `assert_fails_closed` is run twice below: once
against the real workflow, which must pass, and once against a copy with the guard removed, which
must fail. The second call is the negative control, so the check cannot pass by being toothless.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "phoenix-proof.yml"
)


def load_workflow(text: str) -> dict:
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict), "workflow did not parse into a mapping"
    return doc


def proof_steps(doc: dict) -> list[dict]:
    jobs = doc.get("jobs") or {}
    steps: list[dict] = []
    for job in jobs.values():
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                steps.append(step)
    assert steps, "workflow declares no steps"
    return steps


def is_fail_closed_guard(step: dict) -> bool:
    """A step that runs when no contract was declared and exits non-zero."""
    condition = str(step.get("if") or "")
    body = str(step.get("run") or "")
    if "declared" not in condition:
        return False
    # The guard must fire on the absent case, not the declared one.
    absent = "!= 'true'" in condition or "== 'false'" in condition
    if not absent:
        return False
    return "exit 1" in body


def assert_fails_closed(doc: dict) -> None:
    guards = [step for step in proof_steps(doc) if is_fail_closed_guard(step)]
    assert guards, (
        "no step fails the run when .phoenix-ralph/done-check.json is absent, "
        "so phoenix-proof reports SUCCESS having skipped every proof step"
    )
    for guard in guards:
        condition = str(guard.get("if"))
        assert "pull_request" in condition, (
            f"guard {guard.get('name')!r} does not scope itself to pull_request, "
            "so workflow_dispatch runs would fail too"
        )


def test_workflow_fails_when_no_contract_is_declared():
    assert_fails_closed(load_workflow(WORKFLOW.read_text(encoding="utf-8")))


def test_the_guard_is_what_makes_it_pass():
    """Negative control. Strip the guard and the same assertion must fail."""
    doc = load_workflow(WORKFLOW.read_text(encoding="utf-8"))
    stripped = copy.deepcopy(doc)
    for job in (stripped.get("jobs") or {}).values():
        job["steps"] = [
            step
            for step in (job.get("steps") or [])
            if not (isinstance(step, dict) and is_fail_closed_guard(step))
        ]
    with pytest.raises(AssertionError):
        assert_fails_closed(stripped)


def test_proof_steps_are_still_gated_on_the_contract():
    """The fix must not run proof steps that have no check file to read."""
    doc = load_workflow(WORKFLOW.read_text(encoding="utf-8"))
    gated = {
        step.get("name")
        for step in proof_steps(doc)
        if "declared == 'true'" in str(step.get("if") or "")
    }
    for name in (
        "Require base acceptance RED",
        "Require head acceptance GREEN",
        "Prove Phoenix acceptance",
        "Verify Phoenix trace",
    ):
        assert name in gated, f"{name!r} lost its acceptance-contract condition"
