import copy
import hashlib
import importlib.util
import inspect
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "evals" / "harness-eval" / "protocol.json"
PREREGISTRATION_PATH = ROOT / "evals" / "harness-eval" / "preregister.md"
RUNNER_PATH = ROOT / "evals" / "harness-eval" / "run_harness.ps1"
VERIFIER_PATH = ROOT / "evals" / "harness-eval" / "verifiers.py"
RESULTS_PATH = ROOT / "evals" / "harness-eval" / "results"
RUN_MANIFEST_PATH = RESULTS_PATH / "run-manifest.json"
RAW_RUNS_PATH = RESULTS_PATH / "raw-runs.jsonl"

REQUIRED_PINS = {
    "phoenix_source_commit",
    "phoenix_build_stamp",
    "model_id",
    "runner_version",
    "environment_manifest_hash",
    "task_set_hash",
    "seeds",
    "level_1_sealed_verifier_hash",
    "level_2_adversarial_verifier_hash",
}
PLACEHOLDER_PINS = REQUIRED_PINS - {"seeds"}
EXPECTED_TASKS = [
    "cache-lru",
    "csv-parser",
    "date-range",
    "hard-dedupe",
    "hard-slugify",
    "hard-titlecase",
    "hard-truncate",
    "money-round",
    "retry-backoff",
]
EXPECTED_SEEDS = [104729, 130363, 155921, 181081, 205759]
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def load_protocol():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def assert_protocol_valid(protocol):
    assert protocol["schema_version"] == "1.0"
    assert protocol["protocol_status"] == "preregistered"
    assert protocol["execution_status"] == "not_run"
    assert protocol["evidence"]["benchmark_results"] == []
    assert protocol["evidence"]["performance_claims_allowed"] is False

    pins = protocol["pinning"]
    assert REQUIRED_PINS <= pins.keys()
    for name in PLACEHOLDER_PINS:
        pin = pins[name]
        assert pin["state"] == "preregistration_placeholder", name
        assert pin["value"].startswith("PREREGISTRATION_PLACEHOLDER:"), name
        assert pin["replace_before"] == "first_benchmark_run", name
        assert pin["immutable_during_run"] is True, name

    seed_pin = pins["seeds"]
    assert seed_pin["state"] == "preregistered_fixed"
    assert seed_pin["immutable_during_run"] is True
    assert len(seed_pin["values"]) == len(set(seed_pin["values"]))
    assert all(isinstance(seed, int) and seed >= 0 for seed in seed_pin["values"])

    execution = protocol["execution"]
    pairing = execution["pairing"]
    assert execution["arms"] == ["phoenix", "control"]
    assert execution["min_repetitions"] >= 5
    assert execution["repetitions_per_task"] >= execution["min_repetitions"]
    assert len(seed_pin["values"]) == execution["repetitions_per_task"]
    assert pairing["unit"] == ["task_id", "seed"]
    assert pairing["same_task_required"] is True
    assert pairing["same_seed_required"] is True
    assert pairing["one_run_per_arm_required"] is True
    assert pairing["drop_incomplete_pairs"] is True

    mocks = protocol["mocks"]
    assert mocks["classification"] == "mechanics_only"
    assert mocks["performance_evidence_allowed"] is False
    assert mocks["included_in_metrics"] is False

    checks = protocol["checks"]
    assert checks["agent_visible"]
    assert checks["evaluator_only"]
    visible_ids = {check["id"] for check in checks["agent_visible"]}
    evaluator_ids = {check["id"] for check in checks["evaluator_only"]}
    assert visible_ids.isdisjoint(
        evaluator_ids
    ), "agent-visible and evaluator-only check IDs must be disjoint"
    assert all(check["visibility"] == "agent_visible" for check in checks["agent_visible"])
    assert all(check["visibility"] == "evaluator_only" for check in checks["evaluator_only"])
    assert all(check["exposed_to_agent"] is False for check in checks["evaluator_only"])

    evaluator_by_level = {check["level"]: check for check in checks["evaluator_only"]}
    assert evaluator_by_level["level_1_sealed"]["pin"] == "level_1_sealed_verifier_hash"
    assert (
        evaluator_by_level["level_2_adversarial"]["pin"]
        == "level_2_adversarial_verifier_hash"
    )

    metrics = protocol["metrics"]
    assert metrics["primary_output"] == "paired_objective_metrics"
    assert metrics["subjective_assessment"]["ranked_leaderboard"] is False
    assert metrics["subjective_assessment"]["role"] == "secondary_diagnostic_only"
    assert (
        metrics["objective_pass"]["pass_field"]
        == "all_required_sealed_and_adversarial_checks_passed"
    )
    assert metrics["objective_pass"]["numerator"]
    assert metrics["objective_pass"]["denominator"]
    assert metrics["silent_failure"]["numerator"]
    assert metrics["silent_failure"]["denominator"]
    assert {"numerator", "denominator", "rate"} <= set(
        metrics["silent_failure"]["report_components"]
    )
    assert metrics["cost_per_verified_outcome"]["numerator"]
    assert metrics["cost_per_verified_outcome"]["denominator"] == "objective_pass_count"

    intervals = metrics["confidence_intervals"]
    assert intervals["required"] is True
    assert intervals["confidence_level"] == 0.95
    assert intervals["method"] == "paired_bootstrap"
    assert intervals["resamples"] >= 1000
    assert isinstance(intervals["seed"], int)
    assert {
        "objective_pass_rate",
        "silent_failure_rate",
        "cost_per_verified_outcome",
        "paired_arm_differences",
    } <= set(intervals["report_for"])


def mutated_protocol():
    return copy.deepcopy(load_protocol())


def apply_mutation(protocol, operation, path, value=None):
    target = protocol
    for key in path[:-1]:
        target = target[key]

    if operation == "delete":
        del target[path[-1]]
    elif operation == "remove":
        target[path[-1]].remove(value)
    else:
        target[path[-1]] = value


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def canonical_newlines(value):
    return value.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def canonical_hash(value):
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return sha256_bytes(encoded)


def load_json_strict(value):
    def reject_duplicate_keys(pairs):
        result = {}
        for key, item in pairs:
            assert key not in result, f"Duplicate JSON key: {key}"
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=reject_duplicate_keys)


def pin_value(pins, name):
    pin = pins[name]
    assert pin["state"] == "pinned", name
    key = "values" if name == "seeds" else "value"
    assert set(pin) == {key, "state"}, name
    value = pin[key]
    values = value if name == "seeds" else [value]
    assert values and all(item not in (None, "") for item in values), name
    assert all("PREREGISTRATION_PLACEHOLDER" not in str(item) for item in values), name
    return value


def git_blob(commit, path):
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{path.as_posix()}"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"{path} is not recorded by source commit {commit}"
    return result.stdout


def expected_task_manifest(commit):
    task_root = Path("evals") / "swe-bench-lite" / "tasks"
    manifest = []
    for task_id in EXPECTED_TASKS:
        files = {}
        for name in ("problem.md", "solution.py", "test_f2p.py", "test_p2p.py"):
            relative = task_root / task_id / name
            committed = git_blob(commit, relative)
            working = (ROOT / relative).read_bytes()
            assert canonical_newlines(working) == canonical_newlines(committed)
            files[name] = sha256_bytes(working)
        manifest.append({"task_id": task_id, "files": files})
    return manifest


def verifier_hash(function_name):
    spec = importlib.util.spec_from_file_location("harness_eval_verifiers", VERIFIER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return sha256_bytes(inspect.getsource(getattr(module, function_name)).encode())


def parse_timestamp(value):
    assert isinstance(value, str)
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert timestamp.tzinfo is not None and timestamp.utcoffset() is not None
    return timestamp


def expected_prompt(task_id, seed, arm):
    prefix = f"Task {task_id}, seed {seed}. Read problem.md and fix solution.py"
    if arm == "phoenix":
        return (
            f"{prefix} without changing its public API or tests. Use the phoenix MCP tools. "
            "You must call phoenix_sense with the public gate "
            "'python -m pytest test_f2p.py test_p2p.py -q' and require exit 0 before "
            "claiming completion. Do not edit tests. End with DONE only after the public "
            "gate is green."
        )
    return (
        f"{prefix} without changing its public API. End with DONE only when confident "
        "the described behavior is correct."
    )


def test_protocol_is_valid_json_and_satisfies_preregistered_contract():
    assert_protocol_valid(load_protocol())


@pytest.mark.parametrize(
    ("working", "committed", "matches"),
    [
        (b"alpha\r\nbeta\r\n", b"alpha\nbeta\n", True),
        (b"alpha\rbeta\r", b"alpha\nbeta\n", True),
        (b"alpha\r\nbeta\n", b"alpha\nchanged\n", False),
        (b"alpha \r\nbeta\n", b"alpha\nbeta\n", False),
    ],
)
def test_canonical_newlines_only_normalizes_line_endings(working, committed, matches):
    assert (canonical_newlines(working) == canonical_newlines(committed)) is matches


@pytest.mark.parametrize("pin_name", sorted(REQUIRED_PINS))
def test_protocol_rejects_omitted_pinning(pin_name):
    protocol = mutated_protocol()
    del protocol["pinning"][pin_name]

    with pytest.raises((AssertionError, KeyError)):
        assert_protocol_valid(protocol)


def test_protocol_rejects_weakened_minimum_repetitions():
    protocol = mutated_protocol()
    protocol["execution"]["min_repetitions"] = 4
    protocol["execution"]["repetitions_per_task"] = 4
    protocol["pinning"]["seeds"]["values"] = protocol["pinning"]["seeds"]["values"][:4]

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


@pytest.mark.parametrize(
    "requirement",
    ["same_task_required", "same_seed_required", "one_run_per_arm_required"],
)
def test_protocol_rejects_unpaired_task_or_seed(requirement):
    protocol = mutated_protocol()
    protocol["execution"]["pairing"][requirement] = False

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


def test_protocol_rejects_incomplete_arm_pairs():
    protocol = mutated_protocol()
    protocol["execution"]["pairing"]["drop_incomplete_pairs"] = False

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


@pytest.mark.parametrize(
    ("level", "mutation"),
    [
        ("level_1_sealed", {"exposed_to_agent": True}),
        ("level_2_adversarial", {"visibility": "agent_visible"}),
    ],
)
def test_protocol_rejects_exposed_sealed_checks(level, mutation):
    protocol = mutated_protocol()
    check = next(
        check for check in protocol["checks"]["evaluator_only"] if check["level"] == level
    )
    check.update(mutation)

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


def test_protocol_rejects_sealed_check_in_agent_visible_set():
    protocol = mutated_protocol()
    check = copy.deepcopy(protocol["checks"]["evaluator_only"][0])
    protocol["checks"]["agent_visible"].append(check)

    with pytest.raises(
        AssertionError,
        match="agent-visible and evaluator-only check IDs must be disjoint",
    ):
        assert_protocol_valid(protocol)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("classification", "benchmark_equivalent"),
        ("performance_evidence_allowed", True),
        ("included_in_metrics", True),
    ],
)
def test_protocol_rejects_mocks_as_performance_evidence(field, value):
    protocol = mutated_protocol()
    protocol["mocks"][field] = value

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


def test_protocol_rejects_subjective_ranking_as_primary_output():
    protocol = mutated_protocol()
    protocol["metrics"]["primary_output"] = "ranked_subjective_leaderboard"
    protocol["metrics"]["subjective_assessment"]["ranked_leaderboard"] = True
    protocol["metrics"]["subjective_assessment"]["role"] = "primary"

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


@pytest.mark.parametrize(
    ("operation", "path", "value"),
    [
        ("delete", ("metrics", "silent_failure", "denominator"), None),
        (
            "remove",
            ("metrics", "silent_failure", "report_components"),
            "denominator",
        ),
        ("set", ("metrics", "confidence_intervals", "required"), False),
        ("set", ("metrics", "confidence_intervals", "resamples"), 999),
        (
            "remove",
            ("metrics", "confidence_intervals", "report_for"),
            "silent_failure_rate",
        ),
        (
            "delete",
            ("metrics", "cost_per_verified_outcome", "denominator"),
            None,
        ),
        ("delete", ("metrics", "objective_pass", "pass_field"), None),
    ],
    ids=[
        "silent-failure-denominator",
        "silent-failure-report-components-denominator",
        "confidence-intervals-required",
        "confidence-interval-resamples",
        "confidence-interval-silent-failure-rate",
        "cost-per-verified-outcome-denominator",
        "objective-pass-field",
    ],
)
def test_protocol_rejects_weakened_metric_requirements(operation, path, value):
    protocol = mutated_protocol()
    apply_mutation(protocol, operation, path, value)

    with pytest.raises((AssertionError, KeyError)):
        assert_protocol_valid(protocol)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protocol_status", "completed"),
        ("execution_status", "completed"),
    ],
)
def test_protocol_placeholders_cannot_be_completed_evidence(field, value):
    protocol = mutated_protocol()
    protocol[field] = value

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


def test_protocol_rejects_fabricated_result_rows():
    protocol = mutated_protocol()
    protocol["evidence"]["benchmark_results"] = [{"arm": "phoenix", "passed": True}]

    with pytest.raises(AssertionError):
        assert_protocol_valid(protocol)


def test_protocol_preregistration_documents_guardrails():
    text = " ".join(
        PREREGISTRATION_PATH.read_text(encoding="utf-8").lower().split()
    )

    for phrase in (
        "no benchmark run has occurred",
        "preregistration_placeholder",
        "same task and seed",
        "min_repetitions",
        "mechanics_only",
        "not performance evidence",
        "silent-failure numerator",
        "silent-failure denominator",
        "cost per verified outcome",
        "confidence intervals",
        "agent-visible",
        "level-1 sealed",
        "level-2 adversarial",
        "ranked subjective leaderboard is not the primary output",
    ):
        assert phrase in text


def test_real_paired_results_meet_minimum_repetitions():
    assert RUN_MANIFEST_PATH.is_file(), f"Missing {RUN_MANIFEST_PATH.relative_to(ROOT)}"
    assert RAW_RUNS_PATH.is_file(), f"Missing {RAW_RUNS_PATH.relative_to(ROOT)}"

    protocol = load_protocol()
    manifest = load_json_strict(RUN_MANIFEST_PATH.read_text(encoding="utf-8"))
    raw_bytes = RAW_RUNS_PATH.read_bytes()
    raw_text = raw_bytes.decode("utf-8")
    raw_lines = raw_text.splitlines()
    assert len(raw_lines) == 90 and all(line.strip() for line in raw_lines)
    rows = [load_json_strict(line) for line in raw_lines]
    assert all(isinstance(row, dict) for row in rows)
    assert "PLACEHOLDER" not in raw_text.upper()

    assert set(manifest) == {
        "schema_version",
        "protocol_id",
        "protocol_status",
        "execution_status",
        "evidence_classification",
        "tasks",
        "environment",
        "pins",
        "task_manifest",
         "run_count",
    }
    assert manifest["schema_version"] == "1.0"
    assert manifest["protocol_id"] == protocol["protocol_id"]
    assert manifest["protocol_status"] == "preregistered"
    assert manifest["execution_status"] == "completed"
    assert manifest["evidence_classification"] == "benchmark"
    assert manifest["tasks"] == EXPECTED_TASKS
    assert type(manifest["run_count"]) is int and manifest["run_count"] == 90
    assert "PLACEHOLDER" not in json.dumps(manifest).upper()

    pins = manifest["pins"]
    assert set(pins) == REQUIRED_PINS | {
        "runner_hash",
        "raw_jsonl_hash",
        "runner_sha256",
        "completion_utc",
    }
    pinned = {name: pin_value(pins, name) for name in REQUIRED_PINS}
    assert all(type(seed) is int for seed in pinned["seeds"])
    assert pinned["seeds"] == EXPECTED_SEEDS
    assert pinned["model_id"] == "gpt-5.6-sol"
    assert pinned["runner_version"] == "1.0.0"

    source_commit = pinned["phoenix_source_commit"]
    assert GIT_COMMIT.fullmatch(source_commit)
    commit_check = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{source_commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    assert commit_check.returncode == 0, "Pinned Phoenix source commit does not exist"

    task_manifest = expected_task_manifest(source_commit)
    runner_bytes = RUNNER_PATH.read_bytes()
    verifier_bytes = VERIFIER_PATH.read_bytes()
    assert canonical_newlines(runner_bytes) == canonical_newlines(
        git_blob(source_commit, RUNNER_PATH.relative_to(ROOT))
    )
    assert canonical_newlines(verifier_bytes) == canonical_newlines(
        git_blob(source_commit, VERIFIER_PATH.relative_to(ROOT))
    )

    assert manifest["task_manifest"] == task_manifest
    assert pinned["task_set_hash"] == canonical_hash(task_manifest)
    assert pinned["environment_manifest_hash"] == canonical_hash(manifest["environment"])

    runner_sha = sha256_bytes(runner_bytes)
    assert pins["runner_hash"] == runner_sha
    assert pins["runner_sha256"] == runner_sha
    assert pins["raw_jsonl_hash"] == sha256_bytes(raw_bytes)
    parse_timestamp(pins["completion_utc"])

    level1_hash = verifier_hash("level1_sealed")
    level2_hash = verifier_hash("level2_adversarial")
    assert level1_hash != level2_hash
    assert pinned["level_1_sealed_verifier_hash"] == f"sha256:{level1_hash}"
    assert pinned["level_2_adversarial_verifier_hash"] == f"sha256:{level2_hash}"

    row_fields = {
        "run_id",
        "task_id",
        "seed",
        "arm",
        "order",
        "started_utc",
        "completed_utc",
        "exit_code",
        "claimed_done",
        "model_id",
        "runner_sha256",
        "prompt_sha256",
        "transcript_sha256",
        "final_solution_sha256",
        "cost_units",
        "level1_pass",
        "level2_pass",
        "objective_pass",
        "mock_run",
    }
    run_ids = set()
    pairs = defaultdict(dict)
    for row in rows:
        assert set(row) == row_fields
        assert isinstance(row["run_id"], str) and row["run_id"]
        assert row["run_id"] not in run_ids
        run_ids.add(row["run_id"])
        assert row["task_id"] in EXPECTED_TASKS
        assert type(row["seed"]) is int
        assert row["seed"] in EXPECTED_SEEDS
        assert row["arm"] in {"phoenix", "control"}
        assert type(row["order"]) is int
        assert row["order"] in {0, 1}
        assert row["model_id"] == pinned["model_id"]
        assert row["runner_sha256"] == runner_sha
        assert isinstance(row["exit_code"], int) and not isinstance(row["exit_code"], bool)
        assert isinstance(row["claimed_done"], bool)
        assert isinstance(row["level1_pass"], bool)
        assert isinstance(row["level2_pass"], bool)
        assert isinstance(row["objective_pass"], bool)
        assert row["objective_pass"] is (
            row["level1_pass"] and row["level2_pass"]
        )
        assert type(row["cost_units"]) is int and row["cost_units"] == 1
        assert row["mock_run"] is False
        assert parse_timestamp(row["completed_utc"]) >= parse_timestamp(row["started_utc"])
        assert row["prompt_sha256"] == sha256_bytes(
            expected_prompt(row["task_id"], row["seed"], row["arm"]).encode()
        )
        for field in (
            "prompt_sha256",
            "transcript_sha256",
            "final_solution_sha256",
        ):
            assert isinstance(row[field], str) and SHA256.fullmatch(row[field])

        pair = (row["task_id"], row["seed"])
        assert row["arm"] not in pairs[pair]
        pairs[pair][row["arm"]] = row

    expected_pairs = {
        (task_id, seed) for task_id in EXPECTED_TASKS for seed in EXPECTED_SEEDS
    }
    assert set(pairs) == expected_pairs
    for pair, arms in pairs.items():
        assert set(arms) == {"phoenix", "control"}, pair
        assert {row["order"] for row in arms.values()} == {0, 1}, pair
        task_id, seed = pair
        parity = int(sha256_bytes(f"{task_id}{seed}".encode())[-2:], 16) % 2
        expected_order = (
            {"control": 0, "phoenix": 1}
            if parity == 0
            else {"phoenix": 0, "control": 1}
        )
        assert {arm: row["order"] for arm, row in arms.items()} == expected_order
