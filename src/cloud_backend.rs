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
use crate::run_artifacts::{RunArtifacts, Usage};

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

/// What a completed remote task reports about how it ran.
///
/// Every field is optional because a remote may report some, all, or none of them. `None` means
/// "not reported", which is a different fact from a measured zero — the same distinction
/// [`crate::run_artifacts::Usage`] exists to preserve, carried all the way from the wire.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TaskReport {
    pub model: Option<String>,
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub cost_micros: Option<u64>,
}

impl TaskReport {
    /// A completion the remote gave no accounting for.
    pub fn unreported() -> Self {
        Self::default()
    }

    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = Some(model.into());
        self
    }

    pub fn with_tokens(mut self, input: u64, output: u64) -> Self {
        self.input_tokens = Some(input);
        self.output_tokens = Some(output);
        self
    }

    pub fn with_cost(mut self, cost_micros: u64) -> Self {
        self.cost_micros = Some(cost_micros);
        self
    }

    /// The usage half of this report, in the ledger's own type.
    pub fn usage(&self) -> Usage {
        Usage {
            input_tokens: self.input_tokens,
            output_tokens: self.output_tokens,
            cost_micros: self.cost_micros,
        }
    }
}

/// Remote-side state of a dispatched task.
///
/// `Pending` is the only non-terminal variant; the poll loop keeps going only while it sees one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TaskState {
    Pending,
    Succeeded { branch: String, report: TaskReport },
    Failed { reason: String, report: TaskReport },
}

impl TaskState {
    pub fn is_terminal(&self) -> bool {
        !matches!(self, Self::Pending)
    }

    /// Succeeded with no usage accounting from the remote.
    pub fn succeeded(branch: impl Into<String>) -> Self {
        Self::Succeeded { branch: branch.into(), report: TaskReport::unreported() }
    }

    /// Failed with no usage accounting from the remote.
    pub fn failed(reason: impl Into<String>) -> Self {
        Self::Failed { reason: reason.into(), report: TaskReport::unreported() }
    }

    /// What this state reports about how it ran, if it is terminal.
    ///
    /// A failed task still carries a report: tokens burned before the failure are real spend, and a
    /// ledger that drops them under-reports cost precisely on the runs that went wrong.
    pub fn report(&self) -> Option<&TaskReport> {
        match self {
            Self::Pending => None,
            Self::Succeeded { report, .. } | Self::Failed { report, .. } => Some(report),
        }
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
    /// Model and usage come from the remote's own [`TaskReport`]. A field the remote did not report
    /// stays `None` all the way to the ledger: "we were not told" must never become "it was free".
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
                Ok(TaskState::Succeeded { branch, report }) => {
                    return (
                        BackendOutcome::completed(
                            &job.id,
                            CLOUD_BACKEND_NAME,
                            format!("cloud task {} completed on branch {}", task.as_str(), branch),
                        ),
                        apply_report(artifacts.with_branch(branch), &report),
                    )
                }
                Ok(TaskState::Failed { reason, report }) => {
                    let detail = format!("cloud task {} failed: {}", task.as_str(), reason);
                    return (
                        BackendOutcome::failed(&job.id, CLOUD_BACKEND_NAME, detail),
                        apply_report(artifacts.with_error(reason), &report),
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

/// Fold a remote report into the artifact record, preserving unreported-vs-zero.
fn apply_report(mut artifacts: RunArtifacts, report: &TaskReport) -> RunArtifacts {
    if let Some(model) = &report.model {
        artifacts = artifacts.with_model(model.clone());
    }
    let usage = report.usage();
    if usage.is_reported() {
        artifacts = artifacts.with_usage(usage);
    }
    artifacts
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
