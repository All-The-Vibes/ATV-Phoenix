//! `execution_backend` — the ONE contract every Phoenix execution backend implements.
//!
//! Phoenix needs to run a unit of work somewhere: in this process (`local`), on GitHub's
//! Copilot cloud agent, or by automatically picking between them. Rather than letting each
//! call site branch on "where does this run", every destination implements the same
//! [`ExecutionBackend`] trait: hand it a [`Job`], get back a [`BackendOutcome`].
//!
//! This slice defines the contract and the `local` implementation only. The `copilot_cloud`
//! and `auto` backends (cloud dispatch, polling, auto-selection, ledger persistence) are
//! deliberately out of scope here and land in later slices of #80.
//!
//! `LocalBackend` executes commands directly on the local runner (argv, no shell) and
//! reports captured process output in the outcome detail.

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

/// The part of preflight that refused dispatch.
///
/// This enum is non-exhaustive so later slices can add dimensions without forcing
/// downstream exhaustive matches to lie about a safety gate they do not understand.
///
/// There is no `Internal` dimension today because empty refusal sets are rejected before
/// an [`PreflightOutcome::Ineligible`] value can exist; the old fabricated fallback was
/// removed instead of being reclassified.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum PreflightDimension {
    RepositoryEligibility,
    Authentication,
    RunnerCompatibility,
    TaskConstraints,
}

/// One explicit reason a backend refuses to accept a job before execution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreflightRefusal {
    pub dimension: PreflightDimension,
    pub reason: String,
}

impl PreflightRefusal {
    pub fn new(dimension: PreflightDimension, reason: impl Into<String>) -> Self {
        Self {
            dimension,
            reason: reason.into(),
        }
    }
}

/// Refusal reasons for an ineligible preflight.
///
/// The vector is private because "ineligible with no reason" is a fail-open shape:
/// callers often treat an empty reason list as eligible. Use [`Refusals::try_new`] when
/// collecting reasons dynamically, or [`Refusals::new`] when at least one reason is known.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusals {
    reasons: Vec<PreflightRefusal>,
}

/// Attempted to construct an ineligible preflight without any refusal reason.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EmptyRefusals;

impl std::fmt::Display for EmptyRefusals {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("empty refusal set rejected: a refusal with no reason is a fail-open shape")
    }
}

impl std::error::Error for EmptyRefusals {}

impl Refusals {
    pub fn new(first: PreflightRefusal, rest: impl Into<Vec<PreflightRefusal>>) -> Self {
        let mut reasons = vec![first];
        reasons.extend(rest.into());
        Self { reasons }
    }

    pub fn try_new(reasons: impl Into<Vec<PreflightRefusal>>) -> Result<Self, EmptyRefusals> {
        let reasons = reasons.into();
        if reasons.is_empty() {
            Err(EmptyRefusals)
        } else {
            Ok(Self { reasons })
        }
    }

    pub fn as_slice(&self) -> &[PreflightRefusal] {
        &self.reasons
    }
}

/// The pre-dispatch gate for a backend. There is no "maybe": if a backend cannot vouch
/// for every required dimension, the job is ineligible with all known reasons attached.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PreflightOutcome {
    Eligible,
    Ineligible(Refusals),
}

impl PreflightOutcome {
    pub fn eligible() -> Self {
        Self::Eligible
    }

    pub fn ineligible(refusals: Refusals) -> Self {
        Self::Ineligible(refusals)
    }

    pub fn refused(first: PreflightRefusal, rest: impl Into<Vec<PreflightRefusal>>) -> Self {
        Self::Ineligible(Refusals::new(first, rest))
    }

    pub fn try_ineligible(
        reasons: impl Into<Vec<PreflightRefusal>>,
    ) -> Result<Self, EmptyRefusals> {
        Refusals::try_new(reasons).map(Self::Ineligible)
    }

    pub fn is_eligible(&self) -> bool {
        matches!(self, Self::Eligible)
    }

    pub fn reasons(&self) -> &[PreflightRefusal] {
        match self {
            Self::Eligible => &[],
            Self::Ineligible(refusals) => refusals.as_slice(),
        }
    }
}

/// The single execution-backend contract. Object-safe on purpose: call sites hold a
/// `&dyn ExecutionBackend` and stay ignorant of where the work actually runs.
pub trait ExecutionBackend {
    /// Stable identifier for this backend, used in outcomes and (later) in selection.
    fn name(&self) -> &str;

    /// Decide whether this backend may receive `job` at all.
    ///
    /// The default is deliberately fail-closed: a backend that has not implemented preflight
    /// cannot vouch for repository eligibility, authentication, runner compatibility, or task
    /// constraints. Treating that silence as eligible would make the gate useless.
    fn preflight(&self, _job: &Job) -> PreflightOutcome {
        PreflightOutcome::refused(
            PreflightRefusal::new(
                PreflightDimension::RepositoryEligibility,
                format!("{} cannot vouch for repository eligibility", self.name()),
            ),
            vec![
                PreflightRefusal::new(
                    PreflightDimension::Authentication,
                    format!("{} cannot vouch for authentication", self.name()),
                ),
                PreflightRefusal::new(
                    PreflightDimension::RunnerCompatibility,
                    format!("{} cannot vouch for runner compatibility", self.name()),
                ),
                PreflightRefusal::new(
                    PreflightDimension::TaskConstraints,
                    format!("{} cannot vouch for task constraints", self.name()),
                ),
            ],
        )
    }

    /// Run `job` to a terminal outcome. Implementations must not panic on bad input —
    /// an unrunnable job is reported as [`BackendStatus::Failed`].
    fn execute(&self, job: &Job) -> BackendOutcome;
}

/// Stable name of the local backend.
pub const LOCAL_BACKEND_NAME: &str = "local";

/// Runs jobs on the local runner as child processes (argv, no shell).
#[derive(Debug, Clone, Copy, Default)]
pub struct LocalBackend;

impl ExecutionBackend for LocalBackend {
    fn name(&self) -> &str {
        LOCAL_BACKEND_NAME
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
        if job.task.trim().is_empty() {
            return BackendOutcome::failed(&job.id, LOCAL_BACKEND_NAME, "refused: empty task");
        }

        let mut argv = job.task.split_whitespace();
        let program = match argv.next() {
            Some(program) => program,
            None => return BackendOutcome::failed(&job.id, LOCAL_BACKEND_NAME, "refused: empty task"),
        };

        let output = match std::process::Command::new(program).args(argv).output() {
            Ok(output) => output,
            Err(err) => {
                return BackendOutcome::failed(
                    &job.id,
                    LOCAL_BACKEND_NAME,
                    format!("failed to spawn `{}`: {}", program, err),
                );
            }
        };

        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let exit = output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "terminated by signal".to_string());
        let detail = format!("exit={exit}; stdout={stdout:?}; stderr={stderr:?}");

        if output.status.success() {
            BackendOutcome::completed(&job.id, LOCAL_BACKEND_NAME, detail)
        } else {
            BackendOutcome::failed(&job.id, LOCAL_BACKEND_NAME, detail)
        }
    }
}

#[cfg(test)]
mod execution_backend_tests {
    use super::*;

    #[test]
    fn execution_backend_local_dispatch_completes() {
        let backend = LocalBackend;
        let out = backend.execute(&Job::new("job-1", "rustc --version"));

        assert_eq!(out.status, BackendStatus::Completed, "local backend must complete a runnable job");
        assert!(out.is_completed());
        assert_eq!(out.job_id, "job-1", "outcome must echo the job id");
        assert_eq!(out.backend, LOCAL_BACKEND_NAME, "outcome must name the backend that ran it");
        assert!(out.detail.contains("exit=0"), "detail must carry exit status, got {:?}", out.detail);
        assert!(out.detail.contains("stdout="), "detail must carry stdout, got {:?}", out.detail);
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
        let job = Job::new("job-3", "rustc --version");

        assert_eq!(backend.execute(&job), backend.execute(&job), "local backend must be deterministic");
    }

    #[test]
    fn execution_backend_dispatches_through_trait_object() {
        let backend: &dyn ExecutionBackend = &LocalBackend;

        assert_eq!(backend.name(), LOCAL_BACKEND_NAME);
        assert!(
            backend.execute(&Job::new("job-4", "rustc --version")).is_completed(),
            "the contract must be usable behind a trait object"
        );
    }
}
