//! `backend_select` — the `auto` policy that picks where a job runs.
//!
//! [`crate::execution_backend`] defines *how* a backend runs work and *whether* it may accept a job
//! at all (preflight). This module answers the remaining question: given a free-or-full local slot
//! and two candidate backends, which one gets the job — and if neither can take it, exactly why.
//!
//! The rule from #80 is "automatically select cloud when local slots are unavailable and the goal is
//! eligible". Local is preferred whenever it has a slot, because it is in-process, deterministic, and
//! free; cloud is the overflow path, not the default.
//!
//! Two failure modes this deliberately refuses to have:
//!
//! * **Silent fallback.** When the local slot is full and cloud refuses preflight, selection returns
//!   an explicit refusal. It does not quietly run locally anyway — that would break the supervisor's
//!   concurrency bound, which is the one invariant the ready queue exists to hold.
//! * **Fail-open refusal.** A refusal always names every rejected backend and its cause. An empty
//!   rejection list is unrepresentable, mirroring [`crate::execution_backend::Refusals`].
//!
//! Capacity is a *scheduling* fact, not a preflight dimension, so it is modelled separately: a job
//! blocked only by capacity is retryable once a slot frees, while a preflight refusal is not.
//!
//! INVARIANT: selection never returns local when local has no free slot. Silently running locally
//! anyway would break the supervisor's concurrency bound, which is the one invariant the ready
//! queue exists to hold.
//! INVARIANT: a refusal names every rejected backend and its cause; an empty rejection list is
//! unrepresentable, so a fail-open refusal cannot be constructed.

use crate::execution_backend::{ExecutionBackend, Job, Refusals};

/// Stable name of the automatic selection policy.
pub const AUTO_BACKEND_NAME: &str = "auto";

/// Why one candidate backend could not take the job.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RejectionCause {
    /// The backend had no free slot at selection time. Transient: retry when one frees.
    NoCapacity,
    /// The backend's preflight refused the job, with its own reasons attached. Not retryable
    /// until the job or the environment changes.
    Preflight(Refusals),
}

impl RejectionCause {
    /// Whether this rejection could clear on its own once a slot frees.
    pub fn is_transient(&self) -> bool {
        matches!(self, Self::NoCapacity)
    }
}

/// One candidate backend and why it was rejected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackendRejection {
    pub backend: String,
    pub cause: RejectionCause,
}

impl BackendRejection {
    pub fn new(backend: impl Into<String>, cause: RejectionCause) -> Self {
        Self { backend: backend.into(), cause }
    }
}

/// A non-empty set of rejections.
///
/// The vector is private for the same reason `Refusals` hides its own: callers routinely read an
/// empty reason list as "fine, proceed", so "refused for no stated reason" must be unrepresentable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Rejections {
    entries: Vec<BackendRejection>,
}

impl Rejections {
    /// Build from at least one rejection.
    pub fn new(first: BackendRejection, rest: impl Into<Vec<BackendRejection>>) -> Self {
        let mut entries = vec![first];
        entries.extend(rest.into());
        Self { entries }
    }

    pub fn as_slice(&self) -> &[BackendRejection] {
        &self.entries
    }

    /// Whether every candidate was blocked only by capacity.
    ///
    /// True means "retry when a slot frees"; false means at least one backend refused on the merits
    /// and retrying alone will not help. This is the distinction a scheduler needs to avoid spinning
    /// forever on a job that can never run.
    pub fn transient(&self) -> bool {
        self.entries.iter().all(|r| r.cause.is_transient())
    }
}

/// The outcome of the `auto` policy.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Selection {
    /// Dispatch to this backend: it passed preflight and had capacity.
    Backend(String),
    /// No candidate could take the job; every rejection is named.
    Refused(Rejections),
}

impl Selection {
    /// The chosen backend name, if any.
    pub fn backend(&self) -> Option<&str> {
        match self {
            Self::Backend(name) => Some(name),
            Self::Refused(_) => None,
        }
    }

    pub fn is_refused(&self) -> bool {
        matches!(self, Self::Refused(_))
    }
}

/// Pick a backend for `job`, preferring `local` while it has a free slot.
///
/// `local_slot_free` comes from the supervisor's bounded ready queue — selection never queries
/// capacity itself, so the concurrency bound stays owned by one component instead of two.
/// `cloud` is treated as elastic: it is gated by preflight only.
///
/// A backend is selected only if its own `preflight` says eligible, so a backend that cannot vouch
/// for itself (the fail-closed trait default) is never chosen.
pub fn select_backend(
    job: &Job,
    local: &dyn ExecutionBackend,
    cloud: &dyn ExecutionBackend,
    local_slot_free: bool,
) -> Selection {
    let local_rejection = if local_slot_free {
        match local.preflight(job) {
            outcome if outcome.is_eligible() => return Selection::Backend(local.name().to_string()),
            outcome => BackendRejection::new(
                local.name(),
                RejectionCause::Preflight(
                    Refusals::try_new(outcome.reasons().to_vec())
                        .expect("an ineligible preflight always carries at least one reason"),
                ),
            ),
        }
    } else {
        BackendRejection::new(local.name(), RejectionCause::NoCapacity)
    };

    let cloud_outcome = cloud.preflight(job);
    if cloud_outcome.is_eligible() {
        return Selection::Backend(cloud.name().to_string());
    }
    let cloud_rejection = BackendRejection::new(
        cloud.name(),
        RejectionCause::Preflight(
            Refusals::try_new(cloud_outcome.reasons().to_vec())
                .expect("an ineligible preflight always carries at least one reason"),
        ),
    );

    Selection::Refused(Rejections::new(local_rejection, vec![cloud_rejection]))
}
