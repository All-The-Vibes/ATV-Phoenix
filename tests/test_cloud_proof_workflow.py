from copy import deepcopy
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
PROOF_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "phoenix-proof.yml"
SETUP_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "copilot-setup-steps.yml"
DEFAULT_ACCEPTANCE_COMMAND = "python -m pytest tests/test_phoenix_learn.py -q"
CONTRACT_GUARD = "${{ steps.acceptance_contract.outputs.declared == 'true' }}"
UPLOAD_GUARD = "${{ always() && steps.acceptance_contract.outputs.declared == 'true' }}"
GATE_STEP_NAMES = (
    "Require base acceptance RED",
    "Require head acceptance GREEN",
    "Prove Phoenix acceptance",
    "Verify Phoenix trace",
)


def load_workflow(path):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML implements YAML 1.1 and parses the GitHub Actions key "on" as True.
    if True in document and "on" not in document:
        document["on"] = document.pop(True)
    return document


def step_by_name(workflow, name):
    steps = workflow["jobs"]["phoenix-proof"]["steps"]
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1, f"missing or duplicated step: {name}"
    return matches[0]


def workflow_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from workflow_strings(key)
            yield from workflow_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from workflow_strings(item)
    elif isinstance(value, str):
        yield value


def setup_step_by_name(setup, name):
    steps = setup["jobs"]["copilot-setup-steps"]["steps"]
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1, f"missing or duplicated setup step: {name}"
    return matches[0]


def setup_contract(setup=None):
    if setup is None:
        setup = load_workflow(SETUP_WORKFLOW_PATH)
    setup_python = setup_step_by_name(setup, "Set up Python")
    assert "python-version" in setup_python.get("with", {}), "setup Python version"
    return {
        "checkout": setup_step_by_name(setup, "Checkout repository")["uses"],
        "setup_python": setup_python["uses"],
        "python_version": setup_python["with"]["python-version"],
        "rust": setup_step_by_name(setup, "Install Rust")["uses"],
        "rust_cache": setup_step_by_name(setup, "Cache Rust")["uses"],
        "pip_install": setup_step_by_name(setup, "Install Python dependencies")["run"],
    }


def validate_cloud_proof_workflow(workflow, setup=None):
    pins = setup_contract(setup)
    workflow_text = "\n".join(workflow_strings(workflow))
    assert 'encoding="ascii"' not in workflow_text, "workflow ascii encoding"
    assert "encoding='ascii'" not in workflow_text, "workflow ascii encoding"
    assert workflow["permissions"] == {"contents": "read"}, "permissions"
    assert set(workflow["jobs"]) == {"phoenix-proof"}, "jobs"
    job = workflow["jobs"]["phoenix-proof"]
    assert "continue-on-error" not in job, "job continue-on-error"
    assert "if" not in job, "job if"
    assert job["runs-on"] == "ubuntu-latest", "runs-on"

    triggers = workflow["on"]
    assert set(triggers) == {"pull_request", "workflow_dispatch"}, "triggers"
    dispatch = triggers["workflow_dispatch"]
    acceptance_input = dispatch["inputs"]["acceptance_command"]
    assert acceptance_input["default"] == DEFAULT_ACCEPTANCE_COMMAND, "default"
    assert workflow["env"]["PHOENIX_ACCEPTANCE_COMMAND"] == (
        "${{ inputs.acceptance_command || '"
        + DEFAULT_ACCEPTANCE_COMMAND
        + "' }}"
    ), "parameterisable acceptance command"

    checkout = step_by_name(workflow, "Checkout PR head")
    assert checkout["uses"] == pins["checkout"], "checkout pin"
    assert checkout["with"].get("fetch-depth") == 0, "fetch-depth"
    assert "github.event.pull_request.head.sha" in checkout["with"]["ref"], "PR head"

    detect = step_by_name(workflow, "Detect acceptance contract")
    assert "continue-on-error" not in detect, "Detect acceptance contract continue-on-error"
    assert "if" not in detect, "Detect acceptance contract if"
    assert detect["id"] == "acceptance_contract", "contract output id"
    detect_run = detect["run"]
    assert ".phoenix-ralph/done-check.json" in detect_run, "contract path"
    assert "pull_request" in detect_run, "PR contract source"
    assert 'echo "declared=false"' in detect_run, "neutral skip"
    assert detect_run.count('echo "declared=true"') == 2, "contract declared"

    setup_python = step_by_name(workflow, "Set up Python")
    assert setup_python["uses"] == pins["setup_python"], "setup-python pin"
    assert setup_python["with"] == {"python-version": pins["python_version"]}, "Python pin"
    assert step_by_name(workflow, "Install Rust")["uses"] == pins["rust"], "Rust pin"
    assert step_by_name(workflow, "Cache Rust")["uses"] == pins["rust_cache"], "cache pin"
    assert (
        step_by_name(workflow, "Install Python dependencies")["run"]
        == pins["pip_install"]
    ), "pinned pip install"

    prepare = step_by_name(workflow, "Prepare proof inputs")
    assert prepare.get("if") == CONTRACT_GUARD, "Prepare proof inputs if"
    prepare_run = prepare["run"]
    assert "$RUNNER_TEMP/phoenix-check.json" in prepare_run, "temp check file"
    assert 'cp .phoenix-ralph/done-check.json "$RUNNER_TEMP/phoenix-check.json"' in prepare_run
    assert '"target": ["bash", "-lc", os.environ["PHOENIX_ACCEPTANCE_COMMAND"]]' in prepare_run
    assert 'encoding="utf-8"' in prepare_run, "proof input encoding"
    assert "git merge-base" in prepare_run and "PHOENIX_BASE_SHA" in prepare_run, "base"
    assert "PHOENIX_HEAD_SHA" in prepare_run, "head"
    assert "PHOENIX_MCP=$RUNNER_TEMP/phoenix-bin/phoenix-mcp" in prepare_run, "base verifier path"

    build = step_by_name(workflow, "Build Phoenix MCP verifier")
    assert build.get("if") == CONTRACT_GUARD, "Build Phoenix MCP verifier if"
    build_run = build["run"]
    assert 'git checkout --force "$PHOENIX_BASE_SHA"' in build_run, "build from base"
    assert "cargo build --release --locked --bin phoenix-mcp" in build_run, "build"
    assert 'mkdir -p "$RUNNER_TEMP/phoenix-bin"' in build_run, "verifier dir"
    assert 'cp target/release/phoenix-mcp "$PHOENIX_MCP"' in build_run, "verifier copy"
    assert "GITHUB_PATH" not in build_run, "verifier PATH"

    for name in GATE_STEP_NAMES:
        step = step_by_name(workflow, name)
        assert "continue-on-error" not in step, f"{name} continue-on-error"
        assert step.get("if") == CONTRACT_GUARD, f"{name} if"
    for name in ("Prepare proof inputs", "Build Phoenix MCP verifier"):
        assert "continue-on-error" not in step_by_name(workflow, name), f"{name} continue-on-error"

    base_gate = step_by_name(workflow, "Require base acceptance RED")["run"]
    assert 'git checkout --force "$PHOENIX_BASE_SHA"' in base_gate, "base checkout"
    assert 'if "$PHOENIX_MCP" sense "@$PHOENIX_CHECK_FILE"; then' in base_gate, "base RED"
    assert (
        'git checkout "$PHOENIX_HEAD_SHA" -- "$test_file"' in base_gate
    ), "head acceptance test preservation"
    assert "proof is vacuous" in base_gate and "exit 1" in base_gate, "base RED"

    head_gate = step_by_name(workflow, "Require head acceptance GREEN")["run"]
    assert 'git checkout --force "$PHOENIX_HEAD_SHA"' in head_gate, "head checkout"
    assert '"$PHOENIX_MCP" sense "@$PHOENIX_CHECK_FILE"' in head_gate, "head GREEN"
    assert 'if "$PHOENIX_MCP" sense' not in head_gate, "head GREEN"

    accept = step_by_name(workflow, "Prove Phoenix acceptance")["run"]
    assert '"$PHOENIX_MCP" accept "@$PHOENIX_CHECK_FILE"' in accept, "accept"
    assert ' > "$PHOENIX_PROOF_FILE"' in accept, "proof file"
    assert 'read_text(encoding="utf-8")' in accept, "proof read encoding"
    for key in ("saw_red", "green_after_red", "currently_green", "trace_intact"):
        assert f'"{key}"' in accept, key
        assert "is not True" in accept, key

    assert (
        '"$PHOENIX_MCP" verify-trace'
        in step_by_name(workflow, "Verify Phoenix trace")["run"]
    ), "verify-trace"

    upload = step_by_name(workflow, "Upload Phoenix proof artifacts")
    assert "continue-on-error" not in upload, "artifact upload continue-on-error"
    assert upload["uses"] == "actions/upload-artifact@v4", "artifact upload"
    assert upload["if"] == UPLOAD_GUARD, "artifact upload"
    assert upload["with"]["name"] == "phoenix-proof", "artifact upload"
    assert ".phoenix/trace.jsonl" in upload["with"]["path"], "trace artifact"
    assert "${{ env.PHOENIX_PROOF_FILE }}" in upload["with"]["path"], "proof artifact"


def test_cloud_proof_workflow_contract():
    validate_cloud_proof_workflow(load_workflow(PROOF_WORKFLOW_PATH))


def test_done_check_contract_path_is_committable():
    ignored = (ROOT / ".gitignore").read_text(encoding="ascii")
    assert "/.phoenix-ralph/acceptance-contract.json" in ignored
    assert "/.phoenix-ralph/done-check.json" not in ignored


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        (
            lambda workflow: workflow.__setitem__("permissions", {"contents": "write"}),
            "permissions",
        ),
        (
            lambda workflow: step_by_name(workflow, "Checkout PR head")["with"].pop(
                "fetch-depth"
            ),
            "fetch-depth",
        ),
        (
            lambda workflow: step_by_name(workflow, "Detect acceptance contract").update(
                {"run": "echo declared=true\n"}
            ),
            "contract path",
        ),
        (
            lambda workflow: workflow["jobs"]["phoenix-proof"].update(
                {"continue-on-error": True}
            ),
            "job continue-on-error",
        ),
        (
            lambda workflow: workflow["jobs"]["phoenix-proof"].update({"if": "${{ false }}"}),
            "job if",
        ),
        (
            lambda workflow: step_by_name(workflow, "Detect acceptance contract").update(
                {"if": "${{ false }}"}
            ),
            "Detect acceptance contract if",
        ),
        (
            lambda workflow: step_by_name(workflow, "Prove Phoenix acceptance").update(
                {
                    "run": step_by_name(workflow, "Prove Phoenix acceptance")["run"].replace(
                        'read_text(encoding="utf-8")', 'read_text(encoding="ascii")'
                    )
                }
            ),
            "workflow ascii encoding",
        ),
        (
            lambda workflow: step_by_name(workflow, "Require base acceptance RED").update(
                {"name": "Check base"}
            ),
            "Require base acceptance RED",
        ),
        (
            lambda workflow: step_by_name(workflow, "Require base acceptance RED").update(
                {"run": 'git checkout --force "$PHOENIX_BASE_SHA"\n"$PHOENIX_MCP" sense "@$PHOENIX_CHECK_FILE"\n'}
            ),
            "base RED",
        ),
        (
            lambda workflow: step_by_name(workflow, "Require head acceptance GREEN").update(
                {"run": 'git checkout --force "$PHOENIX_HEAD_SHA"\n'}
            ),
            "head GREEN",
        ),
        (
            lambda workflow: workflow["jobs"]["phoenix-proof"]["steps"].remove(
                step_by_name(workflow, "Prove Phoenix acceptance")
            ),
            "Prove Phoenix acceptance",
        ),
        (
            lambda workflow: step_by_name(workflow, "Verify Phoenix trace").update(
                {"run": "echo skip\n"}
            ),
            "verify-trace",
        ),
        (
            lambda workflow: workflow["jobs"]["phoenix-proof"]["steps"].remove(
                step_by_name(workflow, "Upload Phoenix proof artifacts")
            ),
            "Upload Phoenix proof artifacts",
        ),
    ],
)
def test_workflow_validator_rejects_critical_mutations(mutation, expected_fragment):
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    mutation(workflow)
    with pytest.raises(AssertionError) as error:
        validate_cloud_proof_workflow(workflow)
    assert expected_fragment in str(error.value)


@pytest.mark.parametrize("gate_step", GATE_STEP_NAMES)
def test_workflow_validator_rejects_continue_on_error_gate(gate_step):
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    step_by_name(workflow, gate_step)["continue-on-error"] = True
    with pytest.raises(AssertionError, match="continue-on-error"):
        validate_cloud_proof_workflow(workflow)


@pytest.mark.parametrize("gate_step", GATE_STEP_NAMES)
def test_workflow_validator_rejects_falsy_gate_if(gate_step):
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    step_by_name(workflow, gate_step)["if"] = "${{ false }}"
    with pytest.raises(AssertionError, match=f"{gate_step} if"):
        validate_cloud_proof_workflow(workflow)


def test_workflow_validator_rejects_upload_without_contract_guard():
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    step_by_name(workflow, "Upload Phoenix proof artifacts")["if"] = "always()"
    with pytest.raises(AssertionError, match="artifact upload"):
        validate_cloud_proof_workflow(workflow)


def test_workflow_validator_rejects_detect_continue_on_error():
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    step_by_name(workflow, "Detect acceptance contract")["continue-on-error"] = True
    with pytest.raises(AssertionError, match="Detect acceptance contract continue-on-error"):
        validate_cloud_proof_workflow(workflow)


@pytest.mark.parametrize(
    "required_boolean",
    ("saw_red", "green_after_red", "currently_green", "trace_intact"),
)
def test_workflow_validator_rejects_missing_accept_assertion(required_boolean):
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    accept = step_by_name(workflow, "Prove Phoenix acceptance")
    accept["run"] = accept["run"].replace(f'"{required_boolean}"', '"missing_flag"')
    with pytest.raises(AssertionError, match=required_boolean):
        validate_cloud_proof_workflow(workflow)


@pytest.mark.parametrize(
    ("setup_step", "proof_step", "replacement", "expected_fragment"),
    [
        ("Checkout repository", "Checkout PR head", "actions/checkout@v6", "checkout pin"),
        ("Set up Python", "Set up Python", "actions/setup-python@v5", "setup-python pin"),
        ("Install Rust", "Install Rust", "dtolnay/rust-toolchain@stable", "Rust pin"),
        ("Cache Rust", "Cache Rust", "Swatinem/rust-cache@v1", "cache pin"),
    ],
)
def test_workflow_validator_rejects_setup_action_pin_drift(
    setup_step, proof_step, replacement, expected_fragment
):
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    setup = deepcopy(load_workflow(SETUP_WORKFLOW_PATH))
    setup_step_by_name(setup, setup_step)["uses"] = replacement
    with pytest.raises(AssertionError, match=expected_fragment):
        validate_cloud_proof_workflow(workflow, setup=setup)


def test_setup_contract_reports_missing_setup_step_cleanly():
    setup = deepcopy(load_workflow(SETUP_WORKFLOW_PATH))
    setup["jobs"]["copilot-setup-steps"]["steps"].remove(
        setup_step_by_name(setup, "Cache Rust")
    )
    with pytest.raises(AssertionError, match="missing or duplicated setup step: Cache Rust"):
        setup_contract(setup)


@pytest.mark.parametrize(
    ("pinned_value", "replacement"),
    [
        ("3.13.14", "3.13"),
        ("1.94.1", "stable"),
        ("actions/checkout@v7", "actions/checkout@v6"),
        ("actions/setup-python@v6", "actions/setup-python@v5"),
        ("pytest==9.0.2", "pytest"),
        ("PyYAML==6.0.3", "PyYAML"),
        ("iniconfig==2.3.0", "iniconfig"),
        ("packaging==24.2", "packaging"),
        ("pluggy==1.5.0", "pluggy"),
        ("pygments==2.19.1", "pygments"),
    ],
)
def test_workflow_validator_rejects_unpinned_toolchain_mutation(
    pinned_value, replacement
):
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    steps = workflow["jobs"]["phoenix-proof"]["steps"]
    if pinned_value == "3.13.14":
        step_by_name(workflow, "Set up Python")["with"]["python-version"] = replacement
    elif pinned_value.startswith("actions/checkout"):
        step_by_name(workflow, "Checkout PR head")["uses"] = replacement
    elif pinned_value.startswith("actions/setup-python"):
        step_by_name(workflow, "Set up Python")["uses"] = replacement
    elif pinned_value == "1.94.1":
        step_by_name(workflow, "Install Rust")["uses"] = (
            "dtolnay/rust-toolchain@" + replacement
        )
    else:
        install = next(step for step in steps if step.get("name") == "Install Python dependencies")
        install["run"] = install["run"].replace(pinned_value, replacement)

    with pytest.raises(AssertionError):
        validate_cloud_proof_workflow(workflow)


# --- issue #169: the workflow must fail when it has nothing to prove -----------------
#
# Every gated step below is conditioned on the acceptance contract existing on the head.
# With `.phoenix-ralph/done-check.json` absent, all four skipped and the job still concluded
# SUCCESS, so a merge gate reading statusCheckRollup counted a run that proved nothing.
# Measured 2026-08-07 across PRs #159, #160, #162, #164, #166 and #167: all six reported
# phoenix-proof COMPLETED SUCCESS with every proof step skipped.

FAIL_CLOSED_STEP = "Require an acceptance contract"


def fail_closed_guards(workflow):
    """Steps that run when no contract was declared and exit non-zero."""
    guards = []
    for step in workflow["jobs"]["phoenix-proof"]["steps"]:
        condition = str(step.get("if") or "")
        if "declared" not in condition:
            continue
        if "!= 'true'" not in condition and "== 'false'" not in condition:
            continue
        if "exit 1" in str(step.get("run") or ""):
            guards.append(step)
    return guards


def validate_fails_closed(workflow):
    guards = fail_closed_guards(workflow)
    assert guards, (
        "no step fails the run when .phoenix-ralph/done-check.json is absent, so "
        "phoenix-proof reports SUCCESS having skipped every proof step"
    )
    for guard in guards:
        assert "pull_request" in str(guard.get("if")), (
            f"guard {guard.get('name')!r} is not scoped to pull_request, so "
            "workflow_dispatch runs would fail too"
        )


def test_proof_workflow_fails_when_no_contract_is_declared():
    validate_fails_closed(load_workflow(PROOF_WORKFLOW_PATH))


def test_fail_closed_guard_runs_before_the_toolchain_setup():
    """A contract-less run should stop before paying for a Rust build."""
    steps = load_workflow(PROOF_WORKFLOW_PATH)["jobs"]["phoenix-proof"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index(FAIL_CLOSED_STEP) < names.index("Install Rust")


def test_validator_rejects_a_workflow_with_the_guard_removed():
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    job = workflow["jobs"]["phoenix-proof"]
    job["steps"] = [s for s in job["steps"] if s not in fail_closed_guards(workflow)]
    with pytest.raises(AssertionError):
        validate_fails_closed(workflow)


def test_validator_rejects_a_guard_that_fires_on_the_wrong_case():
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    guard = step_by_name(workflow, FAIL_CLOSED_STEP)
    guard["if"] = str(guard["if"]).replace("!= 'true'", "== 'true'")
    with pytest.raises(AssertionError):
        validate_fails_closed(workflow)


def test_validator_rejects_a_guard_that_is_not_scoped_to_pull_requests():
    workflow = deepcopy(load_workflow(PROOF_WORKFLOW_PATH))
    guard = step_by_name(workflow, FAIL_CLOSED_STEP)
    guard["if"] = "${{ steps.acceptance_contract.outputs.declared != 'true' }}"
    with pytest.raises(AssertionError):
        validate_fails_closed(workflow)
