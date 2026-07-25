from copy import deepcopy
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "copilot-setup-steps.yml"
AGENT_PATH = ROOT / ".github" / "agents" / "phoenix-cloud-worker.agent.md"
SLICE_PATHS = (
    ".github/workflows/copilot-setup-steps.yml",
    ".github/agents/phoenix-cloud-worker.agent.md",
    "tests/test_cloud_setup.py",
)
PYTHON_INSTALL_COMMAND = (
    "python -m pip install --quiet --only-binary=:all: "
    "pytest==9.0.2 PyYAML==6.0.3 iniconfig==2.3.0 "
    "packaging==24.2 pluggy==1.5.0 pygments==2.19.1"
)
CLOUD_CONTRACT_COMMAND = "python -m pytest tests/test_cloud_setup.py -q"


def load_workflow(path=WORKFLOW_PATH):
    document = yaml.safe_load(path.read_text(encoding="ascii"))
    # PyYAML implements YAML 1.1 and parses the GitHub Actions key "on" as True.
    if True in document and "on" not in document:
        document["on"] = document.pop(True)
    return document


def load_agent(path=AGENT_PATH):
    text = path.read_text(encoding="ascii")
    assert text.startswith("---\n")
    frontmatter_text, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(frontmatter_text), body.strip()


def validate_workflow(workflow):
    assert set(workflow["jobs"]) == {"copilot-setup-steps"}, "unexpected jobs"
    job = workflow["jobs"]["copilot-setup-steps"]
    assert set(job) == {
        "runs-on",
        "timeout-minutes",
        "permissions",
        "steps",
    }
    assert job["runs-on"] == "ubuntu-latest"
    assert isinstance(job["timeout-minutes"], int)
    assert 0 < job["timeout-minutes"] <= 59, "timeout-minutes exceeds contract"
    assert job["permissions"] == {"contents": "read"}, "permissions are not least privilege"

    triggers = workflow["on"]
    assert "workflow_dispatch" in triggers
    for event in ("push", "pull_request"):
        assert triggers[event] == {"paths": list(SLICE_PATHS)}, (
            f"{event} paths do not cover the complete slice"
        )

    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert uses == [
        "actions/checkout@v7",
        "actions/setup-python@v6",
        "dtolnay/rust-toolchain@1.94.1",
        "Swatinem/rust-cache@v2",
    ], "action or Rust versions do not match the cloud contract"
    python_step = next(
        step for step in job["steps"] if step.get("uses") == "actions/setup-python@v6"
    )
    assert python_step["with"] == {
        "python-version": "3.13.14"
    }, "Python version does not match the cloud contract"
    commands = [step["run"] for step in job["steps"] if "run" in step]
    assert commands == [
        PYTHON_INSTALL_COMMAND,
        CLOUD_CONTRACT_COMMAND,
        "cargo build --release --locked --bin phoenix-mcp",
    ], "setup commands do not match the cloud contract"


def validate_agent(frontmatter, body):
    assert frontmatter["name"] == "phoenix-cloud-worker"
    assert set(frontmatter["tools"]) == {"phoenix/*", "read", "edit", "execute"}
    assert set(frontmatter["mcp-servers"]) == {"phoenix"}
    phoenix = frontmatter["mcp-servers"]["phoenix"]
    assert phoenix == {
        "type": "stdio",
        "command": "./target/release/phoenix-mcp",
        "args": [],
        "tools": ["*"],
        "env": {"PHOENIX_WORKSPACE": "."},
    }

    required_boundaries = (
        "objective evidence",
        "phoenix_sense",
        "Never weaken, replace, or skip a frozen acceptance check.",
        "bounded rollback or retry",
        "phoenix_verify_trace",
        "Keep edits within the requested scope",
        "Return branch evidence",
        "exact checks run and their results",
    )
    assert all(boundary in body for boundary in required_boundaries)


def test_cloud_setup_contract():
    validate_workflow(load_workflow())
    validate_agent(*load_agent())


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        (lambda workflow: workflow["jobs"].update({"extra": {}}), "jobs"),
        (
            lambda workflow: workflow["jobs"]["copilot-setup-steps"][
                "permissions"
            ].update({"issues": "write"}),
            "permissions",
        ),
        (
            lambda workflow: workflow["jobs"]["copilot-setup-steps"].update(
                {"timeout-minutes": 60}
            ),
            "timeout-minutes",
        ),
    ],
)
def test_workflow_validator_rejects_unsafe_mutations(mutation, expected_fragment):
    workflow = deepcopy(load_workflow())
    mutation(workflow)
    with pytest.raises(AssertionError) as error:
        validate_workflow(workflow)
    assert expected_fragment in str(error.value)


@pytest.mark.parametrize("event", ("push", "pull_request"))
@pytest.mark.parametrize("slice_path", SLICE_PATHS)
def test_workflow_validator_rejects_missing_trigger_path(event, slice_path):
    workflow = deepcopy(load_workflow())
    workflow["on"][event]["paths"].remove(slice_path)
    with pytest.raises(AssertionError, match=f"{event} paths"):
        validate_workflow(workflow)


def test_workflow_validator_rejects_cloud_contract_command_mutation():
    workflow = deepcopy(load_workflow())
    steps = workflow["jobs"]["copilot-setup-steps"]["steps"]
    contract_step = next(
        step for step in steps if step.get("run") == CLOUD_CONTRACT_COMMAND
    )
    contract_step["run"] = "python -m pytest tests/test_cloud_setup.py"
    with pytest.raises(AssertionError, match="setup commands"):
        validate_workflow(workflow)


@pytest.mark.parametrize(
    ("pinned_version", "replacement"),
    [
        ("3.13.14", "3.13"),
        ("1.94.1", "stable"),
        ("pytest==9.0.2", "pytest"),
        ("PyYAML==6.0.3", "PyYAML"),
        ("iniconfig==2.3.0", "iniconfig"),
        ("packaging==24.2", "packaging"),
        ("pluggy==1.5.0", "pluggy"),
        ("pygments==2.19.1", "pygments"),
    ],
)
def test_workflow_validator_rejects_pinned_version_mutation(
    pinned_version, replacement
):
    workflow = deepcopy(load_workflow())
    job = workflow["jobs"]["copilot-setup-steps"]
    if pinned_version == "3.13.14":
        python_step = next(
            step for step in job["steps"] if step.get("uses") == "actions/setup-python@v6"
        )
        python_step["with"]["python-version"] = replacement
    elif pinned_version == "1.94.1":
        rust_step = next(
            step
            for step in job["steps"]
            if step.get("uses") == "dtolnay/rust-toolchain@1.94.1"
        )
        rust_step["uses"] = f"dtolnay/rust-toolchain@{replacement}"
    else:
        install_step = next(
            step for step in job["steps"] if step.get("run") == PYTHON_INSTALL_COMMAND
        )
        install_step["run"] = install_step["run"].replace(
            pinned_version, replacement
        )

    with pytest.raises(AssertionError):
        validate_workflow(workflow)


def test_agent_validator_rejects_non_release_binary():
    frontmatter, body = load_agent()
    frontmatter["mcp-servers"]["phoenix"]["command"] = "phoenix-mcp"
    with pytest.raises(AssertionError):
        validate_agent(frontmatter, body)
