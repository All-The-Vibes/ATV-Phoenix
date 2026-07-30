//! Acceptance tests for orphan-lease reconciliation (Part of #81).
//!
//! The bug this prevents is quiet and expensive: a goal stops, its lease stays in the registry, and
//! the slot looks permanently occupied — so a replacement waits forever on a worker that is never
//! coming back. Every test here is a variation on "did the sweep reclaim exactly the right leases,
//! and nothing else?"

use phoenix::lease::LeaseRegistry;
use phoenix::lifecycle::Lifecycle;
use phoenix::reconcile::{reconcile, reconcile_with_audit};

/// A goal that is admitted, running, and holding a live lease.
fn running_with_lease(l: &mut Lifecycle, r: &mut LeaseRegistry, goal: &str, holder: &str) -> u64 {
    l.admit(goal);
    r.acquire(goal, holder, 0, 1000).expect("a fresh goal is leasable").token
}

#[test]
fn a_cancelled_goal_has_its_lease_reclaimed() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    let token = running_with_lease(&mut lifecycle, &mut leases, "g1", "worker-a");
    lifecycle.cancel("g1", "operator stopped it").unwrap();

    let result = reconcile(&mut leases, &lifecycle);

    assert_eq!(result.reclaimed_count(), 1);
    assert!(result.reclaimed_goal("g1"));
    assert_eq!(result.reclaimed[0].token, token, "the dead holder's token is recorded for audit");
    assert_eq!(result.reclaimed[0].holder, "worker-a");
    assert!(leases.current("g1").is_none(), "the slot must actually be free");
}

#[test]
fn a_running_goal_keeps_its_lease() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    running_with_lease(&mut lifecycle, &mut leases, "g1", "worker-a");

    let result = reconcile(&mut leases, &lifecycle);

    assert!(result.is_empty(), "nothing has stopped, so nothing may be reclaimed");
    assert!(leases.current("g1").is_some(), "a live worker must not lose its claim");
}

#[test]
fn a_parked_goal_keeps_its_lease() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    running_with_lease(&mut lifecycle, &mut leases, "g1", "worker-a");
    lifecycle.await_approval("g1").unwrap();

    let result = reconcile(&mut leases, &lifecycle);

    assert!(
        result.is_empty(),
        "'not executing' is not 'finished' - reclaiming here would let a second worker start on \
         work the first has not released"
    );
    assert!(leases.current("g1").is_some());
}

#[test]
fn every_terminal_state_is_reclaimed() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    running_with_lease(&mut lifecycle, &mut leases, "cancelled", "w1");
    running_with_lease(&mut lifecycle, &mut leases, "superseded", "w2");
    running_with_lease(&mut lifecycle, &mut leases, "completed", "w3");
    running_with_lease(&mut lifecycle, &mut leases, "failed", "w4");
    running_with_lease(&mut lifecycle, &mut leases, "still-running", "w5");

    lifecycle.cancel("cancelled", "stop").unwrap();
    lifecycle.supersede("superseded", "rev2").unwrap();
    lifecycle.complete("completed").unwrap();
    lifecycle.fail("failed", "boom").unwrap();

    let result = reconcile(&mut leases, &lifecycle);

    assert_eq!(result.reclaimed_count(), 4, "all four terminal states free their leases");
    for goal in ["cancelled", "superseded", "completed", "failed"] {
        assert!(result.reclaimed_goal(goal), "{goal} should have been reclaimed");
        assert!(leases.current(goal).is_none(), "{goal}'s slot must be free");
    }
    assert!(leases.current("still-running").is_some(), "the live goal is untouched");
}

#[test]
fn a_terminal_goal_holding_no_lease_is_not_reported_as_reclaimed() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    lifecycle.admit("g1");
    lifecycle.cancel("g1", "stopped before it ever acquired").unwrap();

    let result = reconcile(&mut leases, &lifecycle);

    assert!(result.is_empty(), "there was nothing to reclaim, so the sweep did nothing");
}

#[test]
fn the_sweep_is_idempotent() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    running_with_lease(&mut lifecycle, &mut leases, "g1", "worker-a");
    lifecycle.cancel("g1", "stop").unwrap();

    let first = reconcile(&mut leases, &lifecycle);
    assert_eq!(first.reclaimed_count(), 1);

    let second = reconcile(&mut leases, &lifecycle);
    assert!(
        second.is_empty(),
        "a timer-driven sweep that did something different on every run would be unreasonable about"
    );
}

#[test]
fn a_replacement_can_take_the_slot_after_cleanup() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    let dead_token = running_with_lease(&mut lifecycle, &mut leases, "g1", "worker-a");
    lifecycle.cancel("g1", "stop").unwrap();
    reconcile(&mut leases, &lifecycle);

    // The whole point: the slot is genuinely reusable, not just marked clean.
    let fresh = leases
        .acquire("g1", "worker-b", 1, 100)
        .expect("the reclaimed slot must be acquirable immediately");
    assert!(fresh.token > dead_token, "the replacement gets a strictly higher fencing token");
}

#[test]
fn a_zombie_from_a_reclaimed_lease_is_still_fenced() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    let zombie_token = running_with_lease(&mut lifecycle, &mut leases, "g1", "worker-a");
    lifecycle.cancel("g1", "stop").unwrap();
    reconcile(&mut leases, &lifecycle);

    assert!(
        !leases.is_valid("g1", zombie_token, 1),
        "cleanup must not leave the dead holder's token usable"
    );

    let live = leases.acquire("g1", "worker-b", 1, 100).unwrap();
    assert_eq!(
        leases.commit("g1", zombie_token, 2),
        phoenix::lease::Fence::Fenced,
        "reclaiming through the registry's own release path preserves fencing semantics"
    );
    assert_eq!(leases.commit("g1", live.token, 2), phoenix::lease::Fence::Accepted);
}

#[test]
fn an_untracked_lease_is_reported_but_never_reclaimed() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    running_with_lease(&mut lifecycle, &mut leases, "tracked", "w1");
    // A goal holding a lease that the lifecycle has never seen.
    leases.acquire("mystery", "w2", 0, 1000).unwrap();

    let result = reconcile_with_audit(&mut leases, &lifecycle, &["tracked", "mystery"]);

    assert_eq!(result.untracked, vec!["mystery".to_string()]);
    assert!(!result.reclaimed_goal("mystery"), "an untracked lease must not be reclaimed");
    assert!(
        leases.current("mystery").is_some(),
        "most likely a goal admitted between sweeps - reclaiming would race the admission"
    );
}

#[test]
fn the_audit_sweep_still_reclaims_terminal_goals() {
    let mut lifecycle = Lifecycle::new();
    let mut leases = LeaseRegistry::new();
    running_with_lease(&mut lifecycle, &mut leases, "dead", "w1");
    lifecycle.cancel("dead", "stop").unwrap();
    leases.acquire("mystery", "w2", 0, 1000).unwrap();

    let result = reconcile_with_audit(&mut leases, &lifecycle, &["dead", "mystery"]);

    assert!(result.reclaimed_goal("dead"));
    assert!(leases.current("dead").is_none());
    assert_eq!(result.untracked, vec!["mystery".to_string()]);
}

#[test]
fn an_empty_mission_reconciles_to_nothing() {
    let mut leases = LeaseRegistry::new();
    let lifecycle = Lifecycle::new();

    let result = reconcile(&mut leases, &lifecycle);

    assert!(result.is_empty());
    assert_eq!(result.reclaimed_count(), 0);
}
