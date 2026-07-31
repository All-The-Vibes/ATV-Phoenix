//! Acceptance tests for supervisor task identity and withdrawal semantics (Fixes #123, Refs #81).
//!
//! The failure class here is "one logical goal turns into multiple runnable queue entries". A
//! bounded queue without stable identity will over-count retries, swallow work behind a zero limit,
//! and later promote goals whose lifecycle already says "do not execute".

use phoenix::{Admission, Lifecycle, Supervisor};

#[test]
fn re_admitting_an_in_flight_task_is_idempotent() {
    let mut supervisor = Supervisor::with_capacity(2);

    assert_eq!(supervisor.admit("g1"), Admission::Admitted);
    assert_eq!(supervisor.admit("g1"), Admission::Admitted, "a retry must return the existing admission");
    assert_eq!(supervisor.in_flight(), 1, "one goal must hold at most one slot");
    assert_eq!(supervisor.deferred(), 0);
}

#[test]
fn zero_capacity_is_refused_not_silently_swallowed() {
    let mut supervisor = Supervisor::with_capacity(0);

    assert_eq!(supervisor.admit("g1"), Admission::RefusedZeroCapacity);
    assert_eq!(supervisor.in_flight(), 0);
    assert_eq!(supervisor.deferred(), 0, "refused work must not be parked forever");
    assert_eq!(supervisor.next_ready(), None);
}

#[test]
fn a_cancelled_deferred_goal_can_be_withdrawn_before_promotion() {
    let mut supervisor = Supervisor::with_capacity(1);
    let mut lifecycle = Lifecycle::new();

    assert_eq!(supervisor.admit("g1"), Admission::Admitted);
    lifecycle.admit("g1");

    assert_eq!(supervisor.admit("g2"), Admission::Deferred);
    lifecycle.admit("g2");
    lifecycle.cancel("g2", "superseded by operator").unwrap();
    assert!(!lifecycle.should_execute("g2"), "terminal means terminal across modules");

    assert!(supervisor.withdraw("g2"), "a deferred goal needs a withdrawal path");
    assert_eq!(supervisor.deferred(), 0);

    assert!(supervisor.complete("g1"));
    assert_eq!(supervisor.next_ready(), None, "the cancelled deferred goal must not be promoted later");
}

#[test]
fn duplicate_deferral_is_suppressed_so_one_goal_is_handed_out_once() {
    let mut supervisor = Supervisor::with_capacity(1);

    assert_eq!(supervisor.admit("g1"), Admission::Admitted);
    assert_eq!(supervisor.admit("g2"), Admission::Deferred);
    assert_eq!(supervisor.admit("g2"), Admission::Deferred, "retrying a deferred goal must not enqueue it twice");
    assert_eq!(supervisor.deferred(), 1, "one logical goal may occupy at most one deferred slot");

    assert!(supervisor.complete("g1"));
    assert_eq!(supervisor.next_ready(), Some("g2".to_string()));
    assert!(supervisor.complete("g2"));
    assert_eq!(supervisor.next_ready(), None, "the same deferred goal must not be handed out twice");
}

#[test]
fn withdraw_removes_an_in_flight_goal_too() {
    let mut supervisor = Supervisor::with_capacity(1);

    assert_eq!(supervisor.admit("g1"), Admission::Admitted);
    assert!(supervisor.withdraw("g1"));
    assert_eq!(supervisor.in_flight(), 0);
    assert!(!supervisor.withdraw("g1"), "withdrawing twice must report the missing task");
}
