//! `cloud_backend` — the `copilot_cloud` execution backend and the seam that makes it provable.
//!
//! [`crate::execution_backend`] defines the contract; [`crate::backend_select`] decides when cloud
//! is chosen. This module is what actually dispatches — and it exists in two halves on purpose.
//!
//! Cloud dispatch talks to GitHub's Agent Tasks API, which means network, latency, and a remote
//! state machine. None of that can be proven deterministically. So the I/O is pushed behind one
//! narrow trait, [`CloudClient`], and the backend contains only the parts worth proving: how a
//! submitted task's terminal state maps to a [`BackendOutcome`], and what happens when the remote
//! never settles. A test drives a stub client; production drives an HTTP one. The decision logic
//! under test is byte-identical either way.
//!
//! Polling is bounded by `max_polls` rather than a wall clock, so "the remote never settled" is a
//! deterministic outcome instead of a flaky timeout. Running out of polls is [`BackendStatus::Failed`]
//! with the reason attached — never a silent success, and never an unbounded loop.

use crate::execution_backend::{
    BackendOutcome, ExecutionBackend, Job, PreflightDimension, PreflightOutcome, PreflightRefusal,
};
use crate::run_artifacts::RunArtifacts;

/// Stable name of the Copilot cloud backend.
pub const CLOUD_BACKEND_NAME: &str = "copilot_cloud";

/// Default number of poll attempts before a task is declared unsettled.
pub const DEFAULT_MAX_POLLS: u32 = 30;

/// Identifier the remote assigns to a submitted task.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TaskId(pub String);

impl TaskId {
    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Remote-side state of a dispatched task.
///
/// `Pending` is the only non-terminal variant; the poll loop keeps going only while it sees one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TaskState {
    Pending,
    Succeeded { branch: String },
    Failed { reason: String },
}

impl TaskState {
    pub fn is_terminal(&self) -> bool {
        !matches!(self, Self::Pending)
    }
}

/// Why a cloud call could not be completed.
///
/// This is the transport failing, distinct from the *task* failing: a task that ran and failed is
/// [`TaskState::Failed`]. Collapsing the two would let a network blip look like a rejected job.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudError {
    pub message: String,
}

impl CloudError {
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CloudError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CloudError {}

/// The entire remote surface the cloud backend depends on.
///
/// Kept deliberately tiny: submit, then poll. Every additional method here is another thing a test
/// double has to fake and another way production and test can drift apart.
pub trait CloudClient {
    /// Hand `job` to the remote and return the task it created.
    fn submit(&self, job: &Job) -> Result<TaskId, CloudError>;

    /// Read the current state of `task`.
    fn poll(&self, task: &TaskId) -> Result<TaskState, CloudError>;
}

/// Dispatches jobs to GitHub's Copilot cloud agent through a [`CloudClient`].
#[derive(Debug, Clone)]
pub struct CloudBackend<C: CloudClient> {
    client: C,
    max_polls: u32,
}

impl<C: CloudClient> CloudBackend<C> {
    /// Build a backend with the default poll budget.
    pub fn new(client: C) -> Self {
        Self { client, max_polls: DEFAULT_MAX_POLLS }
    }

    /// Build a backend with an explicit poll budget.
    ///
    /// A budget of zero is coerced to one: submitting a task and then never once looking at it
    /// would report failure for work that may well have succeeded, which is a lie the ledger would
    /// then carry forever.
    pub fn with_max_polls(client: C, max_polls: u32) -> Self {
        Self { client, max_polls: max_polls.max(1) }
    }

    /// The poll budget in effect.
    pub fn max_polls(&self) -> u32 {
        self.max_polls
    }

    /// Dispatch `job` and return both the outcome and the structured record of what it produced.
    ///
    /// [`ExecutionBackend::execute`] delegates here rather than duplicating the logic, so the
    /// human-facing outcome and the ledger-facing record can never drift apart and disagree about
    /// the same run — a divergence would be silent and only visible long after the fact.
    ///
    /// Note what is deliberately NOT populated: `model` and `usage` stay unreported, because
    /// [`CloudClient`] does not expose them yet. Filling them with plausible defaults would be
    /// fabrication — [`crate::run_artifacts::Usage`] exists precisely so "the remote never told us"
    /// stays distinguishable from a measured value. They become real when the client contract
    /// carries them.
    pub fn dispatch(&self, job: &Job) -> (BackendOutcome, RunArtifacts) {
        let artifacts = RunArtifacts::none_for(CLOUD_BACKEND_NAME);

        if job.task.trim().is_empty() {
            let reason = "refused: empty task";
            return (
                BackendOutcome::failed(&job.id, CLOUD_BACKEND_NAME, reason),
                artifacts.with_error(reason),
            );
        }

        let task = match self.client.submit(job) {
            Ok(task) => task,
            Err(err) => {
                let reason = format!("submit failed: {err}");
                return (
                    BackendOutcome::failed(&job.id, CLOUD_BACKEND_NAME, reason.clone()),
                    artifacts.with_error(reason),
                );
            }
        };
        let artifacts = artifacts.with_task_id(task.as_str());

        for _ in 0..self.max_polls {
            match self.client.poll(&task) {
                Ok(TaskState::Pending) => continue,
                Ok(TaskState::Succeeded { branch }) => {
                    return (
                        BackendOutcome::completed(
                            &job.id,
                            CLOUD_BACKEND_NAME,
                            format!("cloud task {} completed on branch {}", task.as_str(), branch),
                        ),
                        artifacts.with_branch(branch),
                    )
                }
                Ok(TaskState::Failed { reason }) => {
                    let detail = format!("cloud task {} failed: {}", task.as_str(), reason);
                    return (
                        BackendOutcome::failed(&job.id, CLOUD_BACKEND_NAME, detail),
                        artifacts.with_error(reason),
                    );
                }
                Err(err) => {
                    let detail = format!("poll failed for task {}: {}", task.as_str(), err);
                    return (
                        BackendOutcome::failed(&job.id, CLOUD_BACKEND_NAME, detail.clone()),
                        artifacts.with_error(detail),
                    );
                }
            }
        }

        let detail = format!(
            "cloud task {} did not settle within {} polls",
            task.as_str(),
            self.max_polls
        );
        (
            BackendOutcome::failed(&job.id, CLOUD_BACKEND_NAME, detail.clone()),
            artifacts.with_error(detail),
        )
    }
}

impl<C: CloudClient> ExecutionBackend for CloudBackend<C> {
    fn name(&self) -> &str {
        CLOUD_BACKEND_NAME
    }

    fn preflight(&self, job: &Job) -> PreflightOutcome {
        if job.task.trim().is_empty() {
            return PreflightOutcome::refused(
                PreflightRefusal::new(PreflightDimension::TaskConstraints, "refused: empty task"),
                vec![],
            );
        }
        PreflightOutcome::eligible()
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        self.dispatch(job).0
    }
}
