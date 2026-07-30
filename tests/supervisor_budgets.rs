//! Acceptance tests for per-goal and mission-wide budgets (Part of #81).
//!
//! The properties that matter: a refused charge must not move the counters, a goal running dry must
//! be distinguishable from the mission running dry, and no arithmetic path may wrap an overflow into
//! a number that looks affordable.

use phoenix::budget::{BudgetLedger, Limits, Resource, Scope};

fn ledger(mission: Limits, goal: Limits) -> BudgetLedger {
    BudgetLedger::new(mission, goal)
}

#[test]
fn an_unset_limit_means_unlimited() {
    let mut l = ledger(Limits::unlimited(), Limits::unlimited());

    assert!(l.charge_tokens("g1", u64::MAX).is_ok(), "no limit set means nothing to exceed");
    assert!(l.charge_time("g1", u64::MAX).is_ok());
    for _ in 0..1000 {
        assert!(l.charge_retry("g1").is_ok());
    }
    assert_eq!(l.goal_spend("g1").retries, 1000);
}

#[test]
fn a_goal_can_run_dry_while_the_mission_still_has_room() {
    let mut l = ledger(Limits::unlimited().with_tokens(1000), Limits::unlimited().with_tokens(100));

    assert!(l.charge_tokens("g1", 100).is_ok());
    let err = l.charge_tokens("g1", 1).expect_err("the goal is out of tokens");
    assert_eq!(err.scope, Scope::Goal, "only this goal should stop");
    assert_eq!(err.resource, Resource::Tokens);

    assert!(l.charge_tokens("g2", 100).is_ok(), "a different goal has its own allowance");
}

#[test]
fn the_mission_can_run_dry_while_a_goal_still_looks_fine() {
    let mut l = ledger(Limits::unlimited().with_tokens(150), Limits::unlimited().with_tokens(100));

    assert!(l.charge_tokens("g1", 100).is_ok());
    let err = l.charge_tokens("g2", 100).expect_err("the mission cannot cover this");
    assert_eq!(err.scope, Scope::Mission, "everything must stop, not just this goal");
    assert_eq!(err.resource, Resource::Tokens);
    assert_eq!(l.goal_spend("g2").tokens, 0, "g2 itself had plenty of room");
}

#[test]
fn a_refused_charge_records_nothing() {
    let mut l = ledger(Limits::unlimited().with_tokens(50), Limits::unlimited().with_tokens(50));

    assert!(l.charge_tokens("g1", 40).is_ok());
    assert!(l.charge_tokens("g1", 20).is_err());

    assert_eq!(l.goal_spend("g1").tokens, 40, "a rejected charge must not move the goal counter");
    assert_eq!(
        l.mission_spend().tokens,
        40,
        "nor the mission counter - drift here makes the ledger a fiction"
    );
}

#[test]
fn charging_a_goal_always_charges_the_mission() {
    let mut l = ledger(Limits::unlimited(), Limits::unlimited());

    l.charge_tokens("g1", 30).unwrap();
    l.charge_tokens("g2", 70).unwrap();

    assert_eq!(l.goal_spend("g1").tokens, 30);
    assert_eq!(l.goal_spend("g2").tokens, 70);
    assert_eq!(
        l.mission_spend().tokens,
        100,
        "independent counters would let spend escape one of them"
    );
}

#[test]
fn a_zero_retry_budget_forbids_the_first_retry() {
    let mut l = ledger(Limits::unlimited(), Limits::unlimited().with_retries(0));

    let err = l.charge_retry("g1").expect_err("zero retries means the first attempt is all there is");
    assert_eq!(err.scope, Scope::Goal);
    assert_eq!(err.resource, Resource::Retries);
    assert_eq!(l.goal_spend("g1").retries, 0);
}

#[test]
fn retries_are_counted_at_both_levels() {
    let mut l = ledger(Limits::unlimited().with_retries(3), Limits::unlimited().with_retries(2));

    assert!(l.charge_retry("g1").is_ok());
    assert!(l.charge_retry("g1").is_ok());
    assert_eq!(
        l.charge_retry("g1").expect_err("g1 is out").scope,
        Scope::Goal,
        "the goal limit binds first"
    );

    assert!(l.charge_retry("g2").is_ok(), "g2 has its own retry allowance");
    let err = l.charge_retry("g2").expect_err("the mission total is now exhausted");
    assert_eq!(err.scope, Scope::Mission, "g2 had room; the mission did not");
}

#[test]
fn time_is_budgeted_on_the_same_terms_as_tokens() {
    let mut l = ledger(Limits::unlimited().with_time(100), Limits::unlimited().with_time(60));

    assert!(l.charge_time("g1", 60).is_ok());
    assert_eq!(l.charge_time("g1", 1).expect_err("g1 out of time").resource, Resource::Time);

    assert!(l.charge_time("g2", 40).is_ok());
    let err = l.charge_time("g2", 1).expect_err("mission out of time");
    assert_eq!(err.scope, Scope::Mission);
    assert_eq!(err.resource, Resource::Time);
}

#[test]
fn an_overflowing_charge_reads_as_over_budget_not_affordable() {
    let mut l = ledger(Limits::unlimited().with_tokens(u64::MAX), Limits::unlimited().with_tokens(u64::MAX));

    l.charge_tokens("g1", u64::MAX - 10).unwrap();
    assert!(
        l.charge_tokens("g1", 100).is_err(),
        "saturating arithmetic must not wrap a huge total into a small affordable one"
    );
    assert_eq!(l.goal_spend("g1").tokens, u64::MAX - 10, "the refused charge changed nothing");
}

#[test]
fn check_does_not_mutate_the_ledger() {
    let mut l = ledger(Limits::unlimited().with_tokens(100), Limits::unlimited().with_tokens(100));
    l.charge_tokens("g1", 50).unwrap();

    assert!(l.check_tokens("g1", 10).is_ok());
    assert!(l.check_tokens("g1", 999).is_err());
    assert_eq!(l.goal_spend("g1").tokens, 50, "checking is not spending");
    assert_eq!(l.mission_spend().tokens, 50);
}

#[test]
fn goal_room_reflects_only_the_goal_level() {
    let mut l = ledger(Limits::unlimited().with_tokens(60), Limits::unlimited().with_tokens(50));

    assert!(l.goal_has_room("g1"), "a fresh goal has room");
    l.charge_tokens("g1", 50).unwrap();
    assert!(!l.goal_has_room("g1"), "the goal's own allowance is spent");

    // g2 has spent nothing of its own allowance even though the mission is nearly dry.
    assert!(l.goal_has_room("g2"), "goal-level room is a question about the goal, not the mission");
}

#[test]
fn an_untouched_goal_starts_at_zero() {
    let l = ledger(Limits::unlimited(), Limits::unlimited());
    let spend = l.goal_spend("never-seen");

    assert_eq!(spend.tokens, 0);
    assert_eq!(spend.time, 0);
    assert_eq!(spend.retries, 0);
}

#[test]
fn a_refusal_says_which_scope_and_which_resource() {
    let mut l = ledger(Limits::unlimited(), Limits::unlimited().with_tokens(0));
    let err = l.charge_tokens("g1", 1).unwrap_err();

    let rendered = err.to_string();
    assert!(rendered.contains("goal"), "got {rendered:?}");
    assert!(rendered.contains("tokens"), "got {rendered:?}");
}
