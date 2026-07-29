//! Acceptance tests for the `auto` backend-selection policy (Part of #80).
//!
//! The property that matters is not "auto picks something" — it is that auto never dispatches to a
//! backend that refused preflight, and never silently runs locally when the local slot is full.
//! A selection policy that quietly falls back is worse than no policy: it breaks the supervisor's
//! concurrency bound while looking like it worked.

use phoenix::backend_select::{select_backend, RejectionCause, Selection};
use phoenix::execution_backend::{
    BackendOutcome, ExecutionBackend, Job, PreflightDimension, PreflightOutcome, PreflightRefusal,
};

/// A cloud stand-in whose preflight verdict is fixed by the test.
struct StubCloud {
    eligible: bool,
}

impl ExecutionBackend for StubCloud {
    fn name(&self) -> &str {
        "copilot_cloud"
    }

    fn preflight(&self, _job: &Job) -> PreflightOutcome {
        if self.eligible {
            PreflightOutcome::eligible()
        } else {
            PreflightOutcome::refused(
                PreflightRefusal::new(PreflightDimension::Authentication, "no cloud token"),
                vec![],
            )
        }
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        BackendOutcome::completed(&job.id, self.name(), "cloud executed")
    }
}

/// A backend that implements only the required methods, inheriting the fail-closed default
/// preflight. It can vouch for nothing, so it must never be selected.
struct SilentBackend;

impl ExecutionBackend for SilentBackend {
    fn name(&self) -> &str {
        "silent"
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        BackendOutcome::completed(&job.id, self.name(), "should never run")
    }
}

fn local() -> phoenix::execution_backend::LocalBackend {
    phoenix::execution_backend::LocalBackend
}

#[test]
fn local_is_preferred_while_a_slot_is_free() {
    let job = Job::new("job-1", "do the work");
    let selection = select_backend(&job, &local(), &StubCloud { eligible: true }, true);
    assert_eq!(selection.backend(), Some("local"), "local is cheaper and must win when it can run");
}

#[test]
fn cloud_is_selected_when_the_local_slot_is_full() {
    let job = Job::new("job-2", "do the work");
    let selection = select_backend(&job, &local(), &StubCloud { eligible: true }, false);
    assert_eq!(selection.backend(), Some("copilot_cloud"), "cloud is the overflow path");
}

#[test]
fn a_full_local_slot_never_silently_falls_back_to_local() {
    let job = Job::new("job-3", "do the work");
    let selection = select_backend(&job, &local(), &StubCloud { eligible: false }, false);

    assert!(selection.is_refused(), "no capacity and no eligible cloud must refuse, not run locally");
    assert_eq!(selection.backend(), None, "a refusal must not name a backend to dispatch to");
}

#[test]
fn a_refusal_names_every_rejected_backend_with_a_cause() {
    let job = Job::new("job-4", "do the work");
    let Selection::Refused(rejections) = select_backend(&job, &local(), &StubCloud { eligible: false }, false)
    else {
        panic!("expected a refusal");
    };

    let entries = rejections.as_slice();
    assert_eq!(entries.len(), 2, "both candidates must be accounted for");

    let local_entry = entries.iter().find(|r| r.backend == "local").expect("local must be named");
    assert_eq!(local_entry.cause, RejectionCause::NoCapacity);

    let cloud_entry =
        entries.iter().find(|r| r.backend == "copilot_cloud").expect("cloud must be named");
    match &cloud_entry.cause {
        RejectionCause::Preflight(refusals) => {
            assert!(!refusals.as_slice().is_empty(), "a preflight refusal always states a reason");
            assert!(
                refusals.as_slice().iter().any(|r| r.reason.contains("no cloud token")),
                "the backend's own reason must survive into the selection refusal"
            );
        }
        other => panic!("cloud was rejected for the wrong cause: {other:?}"),
    }
}

#[test]
fn an_ineligible_local_falls_through_to_an_eligible_cloud() {
    let job = Job::new("job-5", "   ");
    let selection = select_backend(&job, &local(), &StubCloud { eligible: true }, true);
    assert_eq!(
        selection.backend(),
        Some("copilot_cloud"),
        "a free slot does not help if local preflight refuses"
    );
}

#[test]
fn capacity_only_refusals_are_distinguishable_from_permanent_ones() {
    let blank = Job::new("job-6", "  ");
    let Selection::Refused(permanent) = select_backend(&blank, &local(), &StubCloud { eligible: false }, true)
    else {
        panic!("expected a refusal");
    };
    assert!(
        !permanent.transient(),
        "both backends refused on the merits; retrying alone can never help"
    );

    let runnable = Job::new("job-7", "real work");
    let Selection::Refused(mixed) = select_backend(&runnable, &local(), &StubCloud { eligible: false }, false)
    else {
        panic!("expected a refusal");
    };
    assert!(
        !mixed.transient(),
        "cloud refused on the merits, so this is not purely a capacity wait"
    );
}

#[test]
fn a_backend_that_cannot_vouch_for_itself_is_never_selected() {
    let job = Job::new("job-8", "real work");

    let selection = select_backend(&job, &SilentBackend, &StubCloud { eligible: true }, true);
    assert_eq!(
        selection.backend(),
        Some("copilot_cloud"),
        "the fail-closed default preflight must keep a silent local backend out of the running"
    );

    let selection = select_backend(&job, &SilentBackend, &SilentBackend, true);
    assert!(selection.is_refused(), "two silent backends can vouch for nothing, so nothing may run");
}

#[test]
fn selection_is_deterministic() {
    let job = Job::new("job-9", "same work");
    let first = select_backend(&job, &local(), &StubCloud { eligible: true }, false);
    let second = select_backend(&job, &local(), &StubCloud { eligible: true }, false);
    assert_eq!(first, second, "the same inputs must always produce the same selection");
}
