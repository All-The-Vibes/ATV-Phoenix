import copy
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "evals" / "harness-eval" / "protocol.json"
PREREGISTRATION_PATH = ROOT / "evals" / "harness-eval" / "preregister.md"

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


def test_protocol_is_valid_json_and_satisfies_preregistered_contract():
    assert_protocol_valid(load_protocol())


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
