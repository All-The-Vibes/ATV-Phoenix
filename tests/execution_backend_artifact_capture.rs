//! Acceptance tests for artifact capture during cloud dispatch (Part of #80).
//!
//! The record and the outcome describe the same run, so the property that matters is that they can
//! never disagree — and that a fact the remote never reported is recorded as absent rather than
//! invented. A ledger that quietly fills gaps is worse than one with holes in it: the holes are
//! visible.

use std::cell::RefCell;

use phoenix::cloud_backend::{CloudBackend, CloudClient, CloudError, TaskId, TaskState, CLOUD_BACKEND_NAME};
use phoenix::execution_backend::{BackendStatus, ExecutionBackend, Job};

struct ScriptedClient {
    submit_result: Result<TaskId, CloudError>,
    polls: RefCell<Vec<Result<TaskState, CloudError>>>,
}

impl ScriptedClient {
    fn new(task_id: &str, polls: Vec<Result<TaskState, CloudError>>) -> Self {
        Self { submit_result: Ok(TaskId::new(task_id)), polls: RefCell::new(polls) }
    }

    fn failing_submit(message: &str) -> Self {
        Self { submit_result: Err(CloudError::new(message)), polls: RefCell::new(Vec::new()) }
    }
}

impl CloudClient for ScriptedClient {
    fn submit(&self, _job: &Job) -> Result<TaskId, CloudError> {
        self.submit_result.clone()
    }

    fn poll(&self, _task: &TaskId) -> Result<TaskState, CloudError> {
        let mut polls = self.polls.borrow_mut();
        if polls.is_empty() {
            Ok(TaskState::Pending)
        } else {
            polls.remove(0)
        }
    }
}

fn job() -> Job {
    Job::new("job-1", "do the cloud work")
}

#[test]
fn a_successful_dispatch_records_task_and_branch_as_fields() {
    let client = ScriptedClient::new(
        "task-abc",
        vec![Ok(TaskState::Pending), Ok(TaskState::Succeeded { branch: "copilot/fix-42".into() })],
    );
    let (outcome, artifacts) = CloudBackend::new(client).dispatch(&job());

    assert_eq!(outcome.status, BackendStatus::Completed);
    assert_eq!(artifacts.backend, CLOUD_BACKEND_NAME);
    assert_eq!(artifacts.task_id.as_deref(), Some("task-abc"));
    assert_eq!(artifacts.branch.as_deref(), Some("copilot/fix-42"));
    assert_eq!(artifacts.error, None, "a completed run records no error");
    assert!(artifacts.was_dispatched());
}

#[test]
fn unreported_facts_are_absent_rather_than_invented() {
    let client =
        ScriptedClient::new("task-abc", vec![Ok(TaskState::Succeeded { branch: "b".into() })]);
    let (_, artifacts) = CloudBackend::new(client).dispatch(&job());

    assert_eq!(artifacts.model, None, "the client contract does not expose a model yet");
    assert!(
        !artifacts.usage.is_reported(),
        "usage the remote never sent must stay unreported, not defaulted to zero"
    );
    assert_eq!(artifacts.usage.total_tokens(), None);
}

#[test]
fn a_remote_task_failure_records_the_reason_and_keeps_the_task_id() {
    let client = ScriptedClient::new(
        "task-def",
        vec![Ok(TaskState::Failed { reason: "runner out of quota".into() })],
    );
    let (outcome, artifacts) = CloudBackend::new(client).dispatch(&job());

    assert_eq!(outcome.status, BackendStatus::Failed);
    assert!(artifacts.was_dispatched(), "it failed after dispatch, so the task id still matters");
    assert_eq!(artifacts.task_id.as_deref(), Some("task-def"));
    assert_eq!(
        artifacts.error.as_deref(),
        Some("runner out of quota"),
        "the record stores the remote's own reason, not the formatted log line"
    );
    assert_eq!(artifacts.branch, None, "a failed run produced no branch");
}

#[test]
fn a_submit_failure_records_no_task_id() {
    let (outcome, artifacts) =
        CloudBackend::new(ScriptedClient::failing_submit("503 service unavailable")).dispatch(&job());

    assert_eq!(outcome.status, BackendStatus::Failed);
    assert!(!artifacts.was_dispatched(), "the remote never accepted the job");
    assert_eq!(artifacts.task_id, None, "inventing an id would fake a dispatch that never happened");
    assert!(artifacts.error.as_deref().unwrap_or_default().contains("503"));
}

#[test]
fn a_refused_job_records_the_refusal_and_never_reaches_the_remote() {
    let client = ScriptedClient::new("task-never", vec![]);
    let (outcome, artifacts) = CloudBackend::new(client).dispatch(&Job::new("job-blank", "   "));

    assert_eq!(outcome.status, BackendStatus::Failed);
    assert_eq!(artifacts.task_id, None);
    assert_eq!(artifacts.error.as_deref(), Some("refused: empty task"));
    assert!(!artifacts.usage.is_reported(), "work never sent cannot have measured cost");
}

#[test]
fn an_unsettled_task_records_the_budget_exhaustion_against_its_task_id() {
    let client = ScriptedClient::new("task-slow", vec![]);
    let (outcome, artifacts) = CloudBackend::with_max_polls(client, 3).dispatch(&job());

    assert_eq!(outcome.status, BackendStatus::Failed);
    assert_eq!(artifacts.task_id.as_deref(), Some("task-slow"), "the stuck task must be traceable");
    let err = artifacts.error.as_deref().unwrap_or_default();
    assert!(err.contains("did not settle"), "got {err:?}");
    assert_eq!(artifacts.branch, None);
}

#[test]
fn a_poll_transport_error_is_recorded_distinctly_from_a_task_failure() {
    let client = ScriptedClient::new(
        "task-ghi",
        vec![Ok(TaskState::Pending), Err(CloudError::new("connection reset"))],
    );
    let (_, artifacts) = CloudBackend::new(client).dispatch(&job());

    let err = artifacts.error.as_deref().unwrap_or_default();
    assert!(err.contains("poll failed"), "the transport must be named as the failing layer");
    assert!(err.contains("connection reset"), "got {err:?}");
}

#[test]
fn execute_and_dispatch_never_disagree_about_the_same_run() {
    // Every terminal path, checked pairwise: the trait method must be exactly dispatch's outcome.
    let cases: Vec<(&str, Vec<Result<TaskState, CloudError>>, Job)> = vec![
        ("task-1", vec![Ok(TaskState::Succeeded { branch: "b".into() })], job()),
        ("task-2", vec![Ok(TaskState::Failed { reason: "nope".into() })], job()),
        ("task-3", vec![Err(CloudError::new("boom"))], job()),
        ("task-4", vec![], Job::new("job-blank", "  ")),
    ];

    for (task_id, polls, j) in cases {
        let via_execute = CloudBackend::with_max_polls(
            ScriptedClient::new(task_id, polls.clone()),
            2,
        )
        .execute(&j);
        let (via_dispatch, _) =
            CloudBackend::with_max_polls(ScriptedClient::new(task_id, polls), 2).dispatch(&j);

        assert_eq!(
            via_execute, via_dispatch,
            "execute must delegate to dispatch, or the log and the ledger can silently diverge"
        );
    }
}

#[test]
fn the_artifact_summary_surfaces_the_recorded_facts() {
    let client =
        ScriptedClient::new("task-sum", vec![Ok(TaskState::Succeeded { branch: "copilot/x".into() })]);
    let (_, artifacts) = CloudBackend::new(client).dispatch(&job());

    let summary = artifacts.summary();
    for expected in ["backend=copilot_cloud", "task=task-sum", "branch=copilot/x"] {
        assert!(summary.contains(expected), "summary must surface {expected:?}, got {summary:?}");
    }
    assert!(!summary.contains("tokens="), "unreported usage must not appear in the summary");
    assert!(!summary.contains("model="), "an unreported model must not appear either");
}
