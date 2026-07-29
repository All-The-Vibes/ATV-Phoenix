//! Acceptance tests for goal leases with fencing tokens (Part of #81).
//!
//! The property that matters is not "a worker can take a lease" — it is that a worker which *lost*
//! its lease can no longer land work. Every test below is deterministic: logical time is passed in,
//! so there is no sleep, no wall clock, and no flake.

use phoenix::lease::{Fence, LeaseDenied, LeaseRegistry, FIRST_TOKEN};

#[test]
fn first_grant_mints_the_first_token() {
    let mut r = LeaseRegistry::new();
    let lease = r.acquire("goal-1", "worker-a", 0, 10).expect("an unheld goal is grantable");
    assert_eq!(lease.token, FIRST_TOKEN);
    assert_eq!(lease.holder, "worker-a");
    assert_eq!(lease.expires_at, 10, "expiry is now + ttl on a logical clock");
}

#[test]
fn tokens_increase_strictly_across_goals() {
    let mut r = LeaseRegistry::new();
    let a = r.acquire("goal-1", "worker-a", 0, 10).unwrap();
    let b = r.acquire("goal-2", "worker-b", 0, 10).unwrap();
    let c = r.acquire("goal-3", "worker-c", 0, 10).unwrap();
    assert!(a.token < b.token && b.token < c.token, "fencing tokens are globally monotonic");
}

#[test]
fn an_unexpired_goal_cannot_be_stolen() {
    let mut r = LeaseRegistry::new();
    r.acquire("goal-1", "worker-a", 0, 10).unwrap();
    assert_eq!(
        r.acquire("goal-1", "worker-b", 9, 10),
        Err(LeaseDenied::Held),
        "a live lease blocks a second holder"
    );
}

#[test]
fn an_expired_goal_is_reassigned_with_a_higher_token() {
    let mut r = LeaseRegistry::new();
    let a = r.acquire("goal-1", "worker-a", 0, 10).unwrap();
    let b = r
        .acquire("goal-1", "worker-b", 10, 10)
        .expect("at expires_at the lease is over and the goal is grantable");
    assert!(b.token > a.token, "takeover mints a strictly higher fencing token");
    assert_eq!(b.holder, "worker-b");
}

#[test]
fn a_stale_holder_is_fenced_after_takeover() {
    let mut r = LeaseRegistry::new();
    let zombie = r.acquire("goal-1", "worker-a", 0, 10).unwrap();
    let live = r.acquire("goal-1", "worker-b", 10, 10).unwrap();

    assert_eq!(
        r.commit("goal-1", zombie.token, 12),
        Fence::Fenced,
        "the zombie must not land work after losing the lease"
    );
    assert_eq!(r.commit("goal-1", live.token, 12), Fence::Accepted);
    assert_eq!(r.watermark("goal-1"), Some(live.token));

    assert_eq!(
        r.commit("goal-1", zombie.token, 12),
        Fence::Fenced,
        "the zombie stays fenced after the watermark advances"
    );
    assert_eq!(r.watermark("goal-1"), Some(live.token), "a fenced write never moves the watermark");
}

#[test]
fn an_expired_holder_cannot_commit() {
    let mut r = LeaseRegistry::new();
    let lease = r.acquire("goal-1", "worker-a", 0, 5).unwrap();
    assert_eq!(r.commit("goal-1", lease.token, 4), Fence::Accepted, "valid while unexpired");
    assert_eq!(
        r.commit("goal-1", lease.token, 5),
        Fence::Fenced,
        "an expired lease may not commit even without a takeover"
    );
}

#[test]
fn only_the_current_token_can_renew() {
    let mut r = LeaseRegistry::new();
    let lease = r.acquire("goal-1", "worker-a", 0, 10).unwrap();

    let renewed = r.renew("goal-1", lease.token, 5, 10).expect("the live holder may extend");
    assert_eq!(renewed.expires_at, 15);
    assert_eq!(renewed.token, lease.token, "renewal keeps the token; it does not mint a new one");

    assert_eq!(
        r.renew("goal-1", lease.token + 99, 5, 10),
        Err(LeaseDenied::Stale),
        "an unknown token may not renew"
    );
    assert_eq!(
        r.renew("goal-1", lease.token, 15, 10),
        Err(LeaseDenied::Stale),
        "an expired holder must re-acquire, not renew"
    );
}

#[test]
fn release_frees_the_goal_only_for_its_owner() {
    let mut r = LeaseRegistry::new();
    let lease = r.acquire("goal-1", "worker-a", 0, 100).unwrap();

    assert!(!r.release("goal-1", lease.token + 1), "a non-owner cannot release the lease");
    assert!(r.is_valid("goal-1", lease.token, 1), "the failed release left ownership intact");

    assert!(r.release("goal-1", lease.token));
    assert!(r.current("goal-1").is_none());

    let next = r
        .acquire("goal-1", "worker-b", 1, 10)
        .expect("release frees the goal before its ttl elapses");
    assert!(next.token > lease.token);
}
