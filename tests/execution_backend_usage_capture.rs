//! Acceptance tests for model and usage capture from the cloud remote (Part of #80).
//!
//! #80 requires capturing "branch artifacts and usage". Branch landed in #107; model and usage were
//! stubbed `None` because the client contract had no way to carry them. This closes that.
//!
//! The property under test is that the wire's own optionality survives intact to the ledger. A
//! remote that reports nothing must stay distinguishable from one that measured zero — otherwise a
//! cost ledger silently claims free runs it never priced.

use std::cell::RefCell;

use phoenix::cloud_backend::{CloudBackend, CloudClient, CloudError, TaskId, TaskReport, TaskState};
use phoenix::execution_backend::{BackendStatus, Job};
use phoenix::run_ledger::RunLedger;
use tempfile::TempDir;

struct ScriptedClient {
    polls: RefCell<Vec<Result<TaskState, CloudError>>>,
}

impl ScriptedClient {
    fn new(polls: Vec<Result<TaskState, CloudError>>) -> Self {
        Self { polls: RefCell::new(polls) }
    }
}

impl CloudClient for ScriptedClient {
    fn submit(&self, _job: &Job) -> Result<TaskId, CloudError> {
        Ok(TaskId::new("task-1"))
    }

    fn poll(&self, _task: &TaskId) -> Result<TaskState, CloudError> {
        let mut p = self.polls.borrow_mut();
        if p.is_empty() { Ok(TaskState::Pending) } else { p.remove(0) }
    }
}

fn job() -> Job {
    Job::new("job-1", "do the work")
}

#[test]
fn a_reported_model_reaches_the_artifacts() {
    let report = TaskReport::unreported().with_model("gpt-5-codex");
    let client =
        ScriptedClient::new(vec![Ok(TaskState::Succeeded { branch: "b".into(), report })]);

    let (_, artifacts) = CloudBackend::new(client).dispatch(&job());
    assert_eq!(artifacts.model.as_deref(), Some("gpt-5-codex"));
}

#[test]
fn reported_tokens_and_cost_reach_the_artifacts() {
    let report = TaskReport::unreported().with_tokens(1200, 340).with_cost(9_500);
    let client =
        ScriptedClient::new(vec![Ok(TaskState::Succeeded { branch: "b".into(), report })]);

    let (_, a) = CloudBackend::new(client).dispatch(&job());
    assert_eq!(a.usage.input_tokens, Some(1200));
    assert_eq!(a.usage.output_tokens, Some(340));
    assert_eq!(a.usage.total_tokens(), Some(1540));
    assert_eq!(a.usage.cost_micros, Some(9_500));
}

#[test]
fn an_unreporting_remote_still_yields_unreported_usage() {
    let client = ScriptedClient::new(vec![Ok(TaskState::succeeded("b"))]);
    let (_, a) = CloudBackend::new(client).dispatch(&job());

    assert_eq!(a.model, None);
    assert!(
        !a.usage.is_reported(),
        "a silent remote must not be recorded as having measured zero"
    );
    assert_eq!(a.usage.total_tokens(), None);
}

#[test]
fn a_partially_reporting_remote_keeps_the_gap_visible() {
    // Model and cost known, token counts not.
    let report = TaskReport::unreported().with_model("gpt-5-codex").with_cost(4_200);
    let client =
        ScriptedClient::new(vec![Ok(TaskState::Succeeded { branch: "b".into(), report })]);

    let (_, a) = CloudBackend::new(client).dispatch(&job());
    assert_eq!(a.model.as_deref(), Some("gpt-5-codex"));
    assert_eq!(a.usage.cost_micros, Some(4_200));
    assert_eq!(a.usage.input_tokens, None);
    assert_eq!(
        a.usage.total_tokens(),
        None,
        "a total cannot be computed honestly from one half"
    );
}

#[test]
fn a_measured_zero_is_distinguishable_from_silence() {
    let measured = TaskReport::unreported().with_tokens(0, 0).with_cost(0);
    let c1 = ScriptedClient::new(vec![Ok(TaskState::Succeeded {
        branch: "b".into(),
        report: measured,
    })]);
    let (_, zeroed) = CloudBackend::new(c1).dispatch(&job());

    let c2 = ScriptedClient::new(vec![Ok(TaskState::succeeded("b"))]);
    let (_, silent) = CloudBackend::new(c2).dispatch(&job());

    assert!(zeroed.usage.is_reported(), "an explicit zero is a measurement");
    assert!(!silent.usage.is_reported());
    assert_ne!(zeroed.usage, silent.usage, "the two must never compare equal");
}

#[test]
fn a_failed_task_still_reports_the_tokens_it_burned() {
    let report = TaskReport::unreported().with_tokens(80, 0).with_cost(300);
    let client = ScriptedClient::new(vec![Ok(TaskState::Failed {
        reason: "runner out of quota".into(),
        report,
    })]);

    let (outcome, a) = CloudBackend::new(client).dispatch(&job());
    assert_eq!(outcome.status, BackendStatus::Failed);
    assert_eq!(a.error.as_deref(), Some("runner out of quota"));
    assert_eq!(
        a.usage.cost_micros,
        Some(300),
        "spend before a failure is real; dropping it under-reports cost on exactly the bad runs"
    );
}

#[test]
fn a_run_that_never_dispatched_reports_no_usage() {
    let client = ScriptedClient::new(vec![]);
    let (_, a) = CloudBackend::new(client).dispatch(&Job::new("j", "   "));

    assert_eq!(a.task_id, None);
    assert!(!a.usage.is_reported(), "work never sent cannot have measured cost");
    assert_eq!(a.model, None);
}

#[test]
fn captured_usage_survives_into_the_run_ledger() {
    let dir = TempDir::new().unwrap();
    let report = TaskReport::unreported().with_model("gpt-5-codex").with_tokens(500, 100).with_cost(2_000);
    let client =
        ScriptedClient::new(vec![Ok(TaskState::Succeeded { branch: "copilot/x".into(), report })]);

    let (_, artifacts) = CloudBackend::new(client).dispatch(&job());
    let ledger = RunLedger::in_mission(dir.path());
    ledger.record("g1", &artifacts).unwrap();

    let read = ledger.read();
    assert!(read.is_intact());
    let e = &read.entries[0];
    assert_eq!(e.model.as_deref(), Some("gpt-5-codex"));
    assert_eq!(e.usage().total_tokens(), Some(600));
    assert_eq!(read.total_cost_micros(), 2_000, "the whole path from wire to ledger is costed");
}

#[test]
fn an_unpriced_run_contributes_nothing_to_ledger_cost() {
    let dir = TempDir::new().unwrap();
    let client = ScriptedClient::new(vec![Ok(TaskState::succeeded("b"))]);
    let (_, artifacts) = CloudBackend::new(client).dispatch(&job());

    let ledger = RunLedger::in_mission(dir.path());
    ledger.record("g1", &artifacts).unwrap();

    assert_eq!(
        ledger.read().total_cost_micros(),
        0,
        "an unpriced run adds nothing - but it is recorded, not dropped"
    );
    assert_eq!(ledger.read().entries.len(), 1);
}

#[test]
fn a_pending_state_reports_nothing() {
    assert!(TaskState::Pending.report().is_none());
    assert!(TaskState::succeeded("b").report().is_some());
    assert!(TaskState::failed("r").report().is_some());
}
