//! Acceptance tests for cloud dispatch through the `CloudClient` seam (Part of #80).
//!
//! The point of the seam is that every branch of dispatch is reachable without a network. These
//! tests drive a scripted client, so a remote that stalls forever, fails mid-poll, or errors on
//! submit are all ordinary deterministic cases rather than things we hope never happen in prod.
//!
//! The poll counter is shared via `Rc<RefCell<_>>` so it stays observable after the client is moved
//! into the backend. Without that, a test claiming "the budget is enforced" could only read the
//! configured value back — which proves nothing about the loop actually stopping.

use std::cell::RefCell;
use std::rc::Rc;

use phoenix::cloud_backend::{
    CloudBackend, CloudClient, CloudError, TaskId, TaskState, CLOUD_BACKEND_NAME,
};
use phoenix::execution_backend::{BackendStatus, ExecutionBackend, Job};

/// A client that replays a scripted sequence of poll results and counts every poll served.
struct ScriptedClient {
    submit_result: Result<TaskId, CloudError>,
    polls: RefCell<Vec<Result<TaskState, CloudError>>>,
    poll_calls: Rc<RefCell<u32>>,
}

impl ScriptedClient {
    fn new(task_id: &str, polls: Vec<Result<TaskState, CloudError>>) -> Self {
        Self {
            submit_result: Ok(TaskId::new(task_id)),
            polls: RefCell::new(polls),
            poll_calls: Rc::new(RefCell::new(0)),
        }
    }

    fn failing_submit(message: &str) -> Self {
        Self {
            submit_result: Err(CloudError::new(message)),
            polls: RefCell::new(Vec::new()),
            poll_calls: Rc::new(RefCell::new(0)),
        }
    }

    /// A client that never settles: the script is empty, so every poll answers `Pending`.
    fn always_pending(task_id: &str) -> Self {
        Self::new(task_id, Vec::new())
    }

    /// A handle to the poll counter that outlives the move into the backend.
    fn counter(&self) -> Rc<RefCell<u32>> {
        Rc::clone(&self.poll_calls)
    }
}

impl CloudClient for ScriptedClient {
    fn submit(&self, _job: &Job) -> Result<TaskId, CloudError> {
        self.submit_result.clone()
    }

    fn poll(&self, _task: &TaskId) -> Result<TaskState, CloudError> {
        *self.poll_calls.borrow_mut() += 1;
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
fn a_succeeded_task_completes_and_reports_its_branch() {
    let client = ScriptedClient::new(
        "task-abc",
        vec![
            Ok(TaskState::Pending),
            Ok(TaskState::succeeded("copilot/fix-42")),
        ],
    );
    let out = CloudBackend::new(client).execute(&job());

    assert_eq!(out.status, BackendStatus::Completed);
    assert_eq!(out.job_id, "job-1", "outcome must echo the job id");
    assert_eq!(out.backend, CLOUD_BACKEND_NAME);
    assert!(out.detail.contains("task-abc"), "detail must carry the task id, got {:?}", out.detail);
    assert!(
        out.detail.contains("copilot/fix-42"),
        "the branch artifact must survive into the outcome, got {:?}",
        out.detail
    );
}

#[test]
fn polling_stops_at_the_first_terminal_state() {
    let client = ScriptedClient::new(
        "task-abc",
        vec![
            Ok(TaskState::Pending),
            Ok(TaskState::succeeded("b")),
            Ok(TaskState::failed("must never be read")),
        ],
    );
    let counter = client.counter();
    let out = CloudBackend::new(client).execute(&job());

    assert!(out.is_completed(), "the first terminal state decides the outcome");
    assert!(!out.detail.contains("must never be read"), "polling must stop once settled");
    assert_eq!(*counter.borrow(), 2, "exactly the polls needed to reach the terminal state");
}

#[test]
fn a_failed_task_reports_the_remote_reason() {
    let client = ScriptedClient::new(
        "task-def",
        vec![Ok(TaskState::failed("runner out of quota"))],
    );
    let out = CloudBackend::new(client).execute(&job());

    assert_eq!(out.status, BackendStatus::Failed);
    assert_eq!(out.job_id, "job-1", "a failed outcome must still echo the job id");
    assert!(
        out.detail.contains("runner out of quota"),
        "the remote's reason must not be swallowed, got {:?}",
        out.detail
    );
}

#[test]
fn an_unsettled_task_fails_within_a_bounded_number_of_polls() {
    let client = ScriptedClient::always_pending("task-slow");
    let counter = client.counter();
    let out = CloudBackend::with_max_polls(client, 5).execute(&job());

    assert_eq!(out.status, BackendStatus::Failed, "never settling is not success");
    assert!(out.detail.contains("did not settle"), "the outcome must say why, got {:?}", out.detail);
    assert!(out.detail.contains("task-slow"), "the stuck task must be identifiable");
    assert_eq!(*counter.borrow(), 5, "the loop must stop at the budget, not spin forever");
}

#[test]
fn a_zero_poll_budget_is_coerced_to_one() {
    let client =
        ScriptedClient::new("task-x", vec![Ok(TaskState::succeeded("b"))]);
    let counter = client.counter();
    let backend = CloudBackend::with_max_polls(client, 0);

    assert_eq!(backend.max_polls(), 1, "submitting and never looking would report a false failure");
    assert!(backend.execute(&job()).is_completed(), "one look is enough to see a settled task");
    assert_eq!(*counter.borrow(), 1);
}

#[test]
fn a_submit_error_is_reported_as_a_transport_failure() {
    let client = ScriptedClient::failing_submit("503 service unavailable");
    let counter = client.counter();
    let out = CloudBackend::new(client).execute(&job());

    assert_eq!(out.status, BackendStatus::Failed);
    assert!(
        out.detail.contains("submit failed") && out.detail.contains("503"),
        "a transport failure must be distinguishable from a rejected task, got {:?}",
        out.detail
    );
    assert_eq!(*counter.borrow(), 0, "a task that was never submitted must never be polled");
}

#[test]
fn a_poll_error_does_not_look_like_a_failed_task() {
    let client = ScriptedClient::new(
        "task-ghi",
        vec![Ok(TaskState::Pending), Err(CloudError::new("connection reset"))],
    );
    let out = CloudBackend::new(client).execute(&job());

    assert_eq!(out.status, BackendStatus::Failed);
    assert!(
        out.detail.contains("poll failed") && out.detail.contains("connection reset"),
        "the transport error must be named as such, got {:?}",
        out.detail
    );
}

#[test]
fn an_unrunnable_job_is_refused_before_any_remote_call() {
    let client = ScriptedClient::new("task-never", vec![]);
    let counter = client.counter();
    let out = CloudBackend::new(client).execute(&Job::new("job-blank", "   "));

    assert_eq!(out.status, BackendStatus::Failed);
    assert!(out.detail.contains("empty task"), "got {:?}", out.detail);
    assert_eq!(*counter.borrow(), 0, "an unrunnable job must not reach the network at all");
}

#[test]
fn preflight_refuses_an_empty_task_and_accepts_a_real_one() {
    let backend = CloudBackend::new(ScriptedClient::new("task-p", vec![]));

    assert!(backend.preflight(&job()).is_eligible(), "a runnable job passes cloud preflight");

    let refused = backend.preflight(&Job::new("job-blank", "  "));
    assert!(!refused.is_eligible());
    assert!(
        !refused.reasons().is_empty(),
        "an ineligible preflight must always state at least one reason"
    );
}

#[test]
fn the_cloud_backend_is_usable_behind_a_trait_object() {
    let concrete = CloudBackend::new(ScriptedClient::new(
        "task-obj",
        vec![Ok(TaskState::succeeded("b"))],
    ));
    let backend: &dyn ExecutionBackend = &concrete;

    assert_eq!(backend.name(), CLOUD_BACKEND_NAME);
    assert!(backend.execute(&job()).is_completed(), "the contract must hold behind dyn dispatch");
}

#[test]
fn task_state_terminality_is_explicit() {
    assert!(!TaskState::Pending.is_terminal(), "pending is the only non-terminal state");
    assert!(TaskState::succeeded("b").is_terminal());
    assert!(TaskState::failed("r").is_terminal());
}

