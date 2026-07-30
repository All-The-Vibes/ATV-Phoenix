//! Acceptance tests for structured run artifacts (Part of #80).
//!
//! The ledger #80 calls for has to persist task IDs, backend decisions, model, usage, and errors as
//! fields. The property under test is that those facts are *typed and separable* — and in particular
//! that "not reported" never silently becomes "zero", because a ledger cannot tell an honest gap
//! from a fabricated measurement after the fact.

use phoenix::run_artifacts::{RunArtifacts, Usage};

#[test]
fn unreported_usage_is_distinguishable_from_zero_usage() {
    let unreported = Usage::unreported();
    assert!(!unreported.is_reported(), "a backend that said nothing must not look like it measured");
    assert_eq!(unreported.total_tokens(), None);

    let measured_zero = Usage::with_tokens(0, 0);
    assert!(measured_zero.is_reported(), "an explicit zero is a real measurement");
    assert_eq!(measured_zero.total_tokens(), Some(0));

    assert_ne!(unreported, measured_zero, "the two must never compare equal");
}

#[test]
fn a_half_known_token_total_is_not_fabricated() {
    let half = Usage { input_tokens: Some(100), output_tokens: None, cost_micros: None };
    assert!(half.is_reported(), "something was reported");
    assert_eq!(
        half.total_tokens(),
        None,
        "treating the missing half as zero would invent a number the ledger would carry as fact"
    );
}

#[test]
fn cost_is_recorded_in_integer_micros() {
    let usage = Usage::with_tokens(10, 20).with_cost(1_234_567);
    assert_eq!(usage.cost_micros, Some(1_234_567), "no float rounding in a ledger");
    assert_eq!(usage.total_tokens(), Some(30));
}

#[test]
fn token_totals_do_not_overflow() {
    let usage = Usage::with_tokens(u64::MAX, 5);
    assert_eq!(usage.total_tokens(), Some(u64::MAX), "saturating, never a wrapped nonsense total");
}

#[test]
fn a_run_that_never_dispatched_has_no_task_id() {
    let artifacts = RunArtifacts::none_for("copilot_cloud");

    assert!(!artifacts.was_dispatched(), "no task id means the remote never accepted the job");
    assert_eq!(artifacts.task_id, None);
    assert_eq!(artifacts.branch, None);
    assert!(!artifacts.usage.is_reported(), "work never sent cannot have cost anything measured");
    assert_eq!(artifacts.backend, "copilot_cloud", "the backend is always known");
}

#[test]
fn a_dispatched_run_carries_its_facts_as_separate_fields() {
    let artifacts = RunArtifacts::none_for("copilot_cloud")
        .with_task_id("task-abc")
        .with_branch("copilot/fix-42")
        .with_model("gpt-5-codex")
        .with_usage(Usage::with_tokens(1200, 340).with_cost(9_500));

    assert!(artifacts.was_dispatched());
    assert_eq!(artifacts.task_id.as_deref(), Some("task-abc"));
    assert_eq!(artifacts.branch.as_deref(), Some("copilot/fix-42"));
    assert_eq!(artifacts.model.as_deref(), Some("gpt-5-codex"));
    assert_eq!(artifacts.usage.total_tokens(), Some(1540));
    assert_eq!(artifacts.usage.cost_micros, Some(9_500));
    assert_eq!(artifacts.error, None, "a successful run records no error");
}

#[test]
fn a_failed_run_records_the_reason_without_losing_what_it_did_produce() {
    let artifacts = RunArtifacts::none_for("copilot_cloud")
        .with_task_id("task-def")
        .with_usage(Usage::with_tokens(80, 0))
        .with_error("runner out of quota");

    assert!(artifacts.was_dispatched(), "it failed after dispatch, so the task id still matters");
    assert_eq!(artifacts.error.as_deref(), Some("runner out of quota"));
    assert_eq!(artifacts.branch, None, "a failed run produced no branch");
    assert_eq!(
        artifacts.usage.total_tokens(),
        Some(80),
        "tokens burned before the failure are still real cost"
    );
}

#[test]
fn the_summary_is_derived_from_fields_and_never_the_source_of_truth() {
    let artifacts = RunArtifacts::none_for("copilot_cloud")
        .with_task_id("task-abc")
        .with_branch("copilot/fix-42")
        .with_model("gpt-5-codex")
        .with_usage(Usage::with_tokens(1000, 200).with_cost(4_200));

    let summary = artifacts.summary();
    for expected in
        ["backend=copilot_cloud", "task=task-abc", "branch=copilot/fix-42", "model=gpt-5-codex"]
    {
        assert!(summary.contains(expected), "summary must surface {expected:?}, got {summary:?}");
    }
    assert!(summary.contains("tokens=1200"), "got {summary:?}");
    assert!(summary.contains("cost_micros=4200"), "got {summary:?}");

    // The fields remain independently readable; nothing needs to parse the prose back out.
    assert_eq!(artifacts.task_id.as_deref(), Some("task-abc"));
}

#[test]
fn a_summary_omits_facts_that_were_never_reported() {
    let summary = RunArtifacts::none_for("local").summary();

    assert_eq!(summary, "backend=local", "absent facts are omitted, not rendered as empty or zero");
    assert!(!summary.contains("tokens"), "an unmeasured run must not display a token count");
    assert!(!summary.contains("error"), "a run with no error must not display one");
}

#[test]
fn a_half_known_usage_is_omitted_from_the_summary_rather_than_guessed() {
    let artifacts = RunArtifacts::none_for("copilot_cloud")
        .with_usage(Usage { input_tokens: Some(50), output_tokens: None, cost_micros: None });

    let summary = artifacts.summary();
    assert!(
        !summary.contains("tokens="),
        "a total that cannot be computed honestly must not appear, got {summary:?}"
    );
}

#[test]
fn artifacts_are_comparable_for_ledger_deduplication() {
    let a = RunArtifacts::none_for("copilot_cloud").with_task_id("task-1");
    let b = RunArtifacts::none_for("copilot_cloud").with_task_id("task-1");
    let c = RunArtifacts::none_for("copilot_cloud").with_task_id("task-2");

    assert_eq!(a, b, "identical records must compare equal so the ledger can dedupe");
    assert_ne!(a, c);
}
