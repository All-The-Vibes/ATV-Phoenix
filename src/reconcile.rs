//! `reconcile` — reclaiming leases held by goals that are no longer live.
//!
//! [`crate::lease`] hands out exclusive claims; [`crate::lifecycle`] decides when a goal stops. Left
//! unjoined, those two disagree in a specific and expensive way: a goal gets cancelled, but the lease
//! it held stays in the registry. Nothing ever reclaims it, so the goal's slot looks permanently
//! occupied and any replacement waits forever on a worker that is never coming back.
//!
//! Reconciliation is the sweep that closes that gap. It answers one question — "which leases are held
//! by goals that already reached a terminal state?" — and reclaims exactly those.
//!
//! Three properties this deliberately holds:
//!
//! * **Only terminal goals are reclaimed.** A goal that is merely *parked* (`AwaitingApproval`) still
//!   legitimately owns its lease; reclaiming it would let a second worker start on work the first has
//!   not released. "Not executing" is not "finished".
//! * **A lease with no lifecycle record is left alone.** It is more likely a goal admitted between two
//!   sweeps than a genuine orphan, and reclaiming it would race the admission. Untracked is reported,
//!   never reclaimed — the caller decides.
//! * **Reclaiming uses the registry's own release path**, so the fencing watermark keeps its meaning:
//!   a zombie worker that wakes up after cleanup is fenced out by token arithmetic exactly as it
//!   would have been by a normal handover.

use crate::lease::LeaseRegistry;
use crate::lifecycle::Lifecycle;

/// One lease reclaimed from a goal that had already stopped.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReclaimedLease {
    pub goal: String,
    /// The fencing token the dead holder had. Recorded so an audit can tell which worker was fenced.
    pub token: u64,
    pub holder: String,
}

/// What a reconciliation sweep found and did.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Reconciliation {
    /// Leases reclaimed from terminal goals.
    pub reclaimed: Vec<ReclaimedLease>,
    /// Goals holding a lease with no lifecycle record at all.
    ///
    /// Reported rather than reclaimed: most likely a goal admitted between sweeps, and reclaiming it
    /// would race that admission. Surfacing it lets a caller investigate a genuine leak without the
    /// sweep silently causing one.
    pub untracked: Vec<String>,
}

impl Reconciliation {
    /// Whether the sweep changed anything.
    pub fn is_empty(&self) -> bool {
        self.reclaimed.is_empty() && self.untracked.is_empty()
    }

    pub fn reclaimed_count(&self) -> usize {
        self.reclaimed.len()
    }

    /// Whether `goal`'s lease was reclaimed by this sweep.
    pub fn reclaimed_goal(&self, goal: &str) -> bool {
        self.reclaimed.iter().any(|r| r.goal == goal)
    }
}

/// Reclaim every lease whose goal has already reached a terminal state.
///
/// Idempotent: a second sweep over the same state reclaims nothing, because the first already
/// released those leases. That matters for a supervisor that sweeps on a timer — a cleanup pass that
/// did something different on every run would be impossible to reason about.
pub fn reconcile(leases: &mut LeaseRegistry, lifecycle: &Lifecycle) -> Reconciliation {
    let mut out = Reconciliation::default();

    // Terminal goals are the cleanup worklist; a lease is only interesting if one is actually held.
    for goal in lifecycle.terminal_goals() {
        if let Some(lease) = leases.current(goal) {
            let record =
                ReclaimedLease { goal: goal.to_string(), token: lease.token, holder: lease.holder.clone() };
            // Release through the registry's own owner-checked path, preserving fencing semantics.
            if leases.release(goal, record.token) {
                out.reclaimed.push(record);
            }
        }
    }

    out
}

/// Reclaim terminal-goal leases and also report leases held by goals the lifecycle has never seen.
///
/// `known_goals` is the set the caller believes is tracked. Anything holding a lease outside both
/// that set and the lifecycle is surfaced in [`Reconciliation::untracked`] — never reclaimed.
pub fn reconcile_with_audit(
    leases: &mut LeaseRegistry,
    lifecycle: &Lifecycle,
    leased_goals: &[&str],
) -> Reconciliation {
    let mut out = reconcile(leases, lifecycle);

    for goal in leased_goals {
        if lifecycle.state(goal).is_none() && leases.current(goal).is_some() {
            out.untracked.push((*goal).to_string());
        }
    }
    out.untracked.sort();
    out.untracked.dedup();

    out
}
