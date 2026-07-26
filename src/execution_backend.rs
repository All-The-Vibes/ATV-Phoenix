//! `execution_backend` — the ONE contract every Phoenix execution backend implements.
//!
//! Phoenix needs to run a unit of work somewhere: in this process (`local`), on GitHub's
//! Copilot cloud agent, or by automatically picking between them. Rather than letting each
//! call site branch on "where does this run", every destination implements the same
//! [`ExecutionBackend`] trait: hand it a [`Job`], get back a [`BackendOutcome`].
//!
//! This slice defines the contract and the `local` implementation only. The `copilot_cloud`
//! and `auto` backends (cloud dispatch, polling, preflight, auto-selection, ledger
//! persistence) are deliberately out of scope here and land in later slices of #80.
//!
//! `LocalBackend` is in-process and deterministic on purpose: no subprocess, no network,
//! no clock. The same `Job` always yields the same `BackendOutcome`, so it is the honest
//! baseline the other backends are compared against.

/// A unit of work handed to an execution backend.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Job {
    /// Caller-supplied identifier, echoed back on the outcome so a result can be correlated.
    pub id: String,
    /// The work to perform. An empty/whitespace-only task is not runnable.
    pub task: String,
}

impl Job {
    pub fn new(id: impl Into<String>, task: impl Into<String>) -> Self {
        Self { id: id.into(), task: task.into() }
    }
}

/// Terminal status of a dispatched job. A backend reports exactly one of these — there is no
/// "unknown": an outcome the backend cannot vouch for is [`BackendStatus::Failed`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BackendStatus {
    Completed,
    Failed,
}

/// What a backend reports back for one job.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackendOutcome {
    /// Echo of [`Job::id`], so an outcome is always traceable to its job.
    pub job_id: String,
    /// Which backend produced this outcome (e.g. `"local"`).
    pub backend: String,
    pub status: BackendStatus,
    /// Human-readable result or failure reason.
    pub detail: String,
}

impl BackendOutcome {
    pub fn completed(job_id: impl Into<String>, backend: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            job_id: job_id.into(),
            backend: backend.into(),
            status: BackendStatus::Completed,
            detail: detail.into(),
        }
    }

    pub fn failed(job_id: impl Into<String>, backend: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            job_id: job_id.into(),
            backend: backend.into(),
            status: BackendStatus::Failed,
            detail: detail.into(),
        }
    }

    pub fn is_completed(&self) -> bool {
        self.status == BackendStatus::Completed
    }
}

/// The single execution-backend contract. Object-safe on purpose: call sites hold a
/// `&dyn ExecutionBackend` and stay ignorant of where the work actually runs.
pub trait ExecutionBackend {
    /// Stable identifier for this backend, used in outcomes and (later) in selection.
    fn name(&self) -> &str;

    /// Run `job` to a terminal outcome. Implementations must not panic on bad input —
    /// an unrunnable job is reported as [`BackendStatus::Failed`].
    fn execute(&self, job: &Job) -> BackendOutcome;
}

/// Stable name of the local backend.
pub const LOCAL_BACKEND_NAME: &str = "local";

/// Runs jobs in this process, deterministically. No subprocess, no network.
#[derive(Debug, Clone, Copy, Default)]
pub struct LocalBackend;

impl ExecutionBackend for LocalBackend {
    fn name(&self) -> &str {
        LOCAL_BACKEND_NAME
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        if job.task.trim().is_empty() {
            return BackendOutcome::failed(&job.id, LOCAL_BACKEND_NAME, "refused: empty task");
        }
        BackendOutcome::completed(
            &job.id,
            LOCAL_BACKEND_NAME,
            format!("local executed: {}", job.task.trim()),
        )
    }
}

#[cfg(test)]
mod execution_backend_tests {
    use super::*;

    #[test]
    fn execution_backend_local_dispatch_completes() {
        let backend = LocalBackend;
        let out = backend.execute(&Job::new("job-1", "sum 2 and 2"));

        assert_eq!(out.status, BackendStatus::Completed, "local backend must complete a runnable job");
        assert!(out.is_completed());
        assert_eq!(out.job_id, "job-1", "outcome must echo the job id");
        assert_eq!(out.backend, LOCAL_BACKEND_NAME, "outcome must name the backend that ran it");
        assert!(out.detail.contains("sum 2 and 2"), "detail must carry the executed task, got {:?}", out.detail);
    }

    #[test]
    fn execution_backend_reports_outcome_for_unrunnable_job() {
        let backend = LocalBackend;
        let out = backend.execute(&Job::new("job-2", "   "));

        assert_eq!(out.status, BackendStatus::Failed, "a blank task is not runnable");
        assert!(!out.is_completed());
        assert_eq!(out.job_id, "job-2", "a failed outcome must still echo the job id");
        assert_eq!(out.backend, LOCAL_BACKEND_NAME);
        assert!(out.detail.contains("empty task"), "failure must state the reason, got {:?}", out.detail);
    }

    #[test]
    fn execution_backend_local_is_deterministic() {
        let backend = LocalBackend;
        let job = Job::new("job-3", "same work");

        assert_eq!(backend.execute(&job), backend.execute(&job), "local backend must be deterministic");
    }

    #[test]
    fn execution_backend_dispatches_through_trait_object() {
        let backend: &dyn ExecutionBackend = &LocalBackend;

        assert_eq!(backend.name(), LOCAL_BACKEND_NAME);
        assert!(
            backend.execute(&Job::new("job-4", "via trait object")).is_completed(),
            "the contract must be usable behind a trait object"
        );
    }
}
