//! Acceptance tests for goal cancellation, supersession, and approval gating (Part of #81).
//!
//! The property under test is terminality. A supervisor that can revive a cancelled goal does not
//! have cancellation, it has a suggestion — so every one of these tests is really asking the same
//! question from a different angle: can a decided outcome be undone?

use phoenix::lifecycle::{GoalState, Lifecycle, TransitionDenied};

fn running() -> Lifecycle {
    let mut l = Lifecycle::new();
    l.admit("g1");
    l
}

#[test]
fn an_admitted_goal_starts_running_and_should_execute() {
    let l = running();
    assert_eq!(l.state("g1"), Some(&GoalState::Running));
    assert!(l.should_execute("g1"));
}

#[test]
fn an_untracked_goal_has_no_mandate_to_execute() {
    let l = Lifecycle::new();
    assert_eq!(l.state("ghost"), None);
    assert!(!l.should_execute("ghost"), "a worker that cannot find its goal must not proceed");
}

#[test]
fn a_cancelled_goal_stops_executing_and_keeps_its_reason() {
    let mut l = running();
    l.cancel("g1", "operator aborted the mission").unwrap();

    match l.state("g1") {
        Some(GoalState::Cancelled { reason }) => assert_eq!(reason, "operator aborted the mission"),
        other => panic!("expected Cancelled, got {other:?}"),
    }
    assert!(!l.should_execute("g1"));
}

#[test]
fn a_cancelled_goal_can_never_be_revived() {
    let mut l = running();
    l.cancel("g1", "stop").unwrap();

    for attempt in [
        l.approve("g1"),
        l.complete("g1"),
        l.await_approval("g1"),
        l.fail("g1", "late failure"),
    ] {
        match attempt {
            Err(TransitionDenied::AlreadyTerminal { current }) => {
                assert!(matches!(current, GoalState::Cancelled { .. }), "got {current:?}");
            }
            other => panic!("a terminal goal must refuse every transition, got {other:?}"),
        }
    }

    assert!(matches!(l.state("g1"), Some(GoalState::Cancelled { .. })), "state must be unchanged");
}

#[test]
fn re_admitting_does_not_resurrect_a_cancelled_goal() {
    let mut l = running();
    l.cancel("g1", "stop").unwrap();

    let state = l.admit("g1");
    assert!(
        matches!(state, GoalState::Cancelled { .. }),
        "an idempotent retry of 'start this goal' must not undo a cancellation, got {state:?}"
    );
    assert!(!l.should_execute("g1"));
}

#[test]
fn supersession_records_the_replacement() {
    let mut l = running();
    l.supersede("g1", "g1-rev2").unwrap();

    match l.state("g1") {
        Some(GoalState::Superseded { by }) => assert_eq!(by, "g1-rev2"),
        other => panic!("expected Superseded, got {other:?}"),
    }
    assert!(!l.should_execute("g1"), "superseded work must stop");
}

#[test]
fn a_goal_cannot_supersede_itself() {
    let mut l = running();
    assert_eq!(
        l.supersede("g1", "g1"),
        Err(TransitionDenied::SelfSupersession),
        "self-supersession would make a goal its own replacement and orphan the work"
    );
    assert_eq!(l.state("g1"), Some(&GoalState::Running), "the refused transition changed nothing");
}

#[test]
fn a_superseded_goal_is_terminal_too() {
    let mut l = running();
    l.supersede("g1", "g1-rev2").unwrap();
    assert!(matches!(l.cancel("g1", "too late"), Err(TransitionDenied::AlreadyTerminal { .. })));
}

#[test]
fn a_parked_goal_is_live_but_must_not_execute() {
    let mut l = running();
    l.await_approval("g1").unwrap();

    assert_eq!(l.state("g1"), Some(&GoalState::AwaitingApproval));
    assert!(
        !l.should_execute("g1"),
        "conflating 'not finished' with 'keep working' runs a goal through the gate it was parked at"
    );
    assert!(l.state("g1").unwrap().is_live(), "it is parked, not finished");
}

#[test]
fn approval_resumes_a_parked_goal() {
    let mut l = running();
    l.await_approval("g1").unwrap();
    l.approve("g1").unwrap();

    assert_eq!(l.state("g1"), Some(&GoalState::Running));
    assert!(l.should_execute("g1"));
}

#[test]
fn a_parked_goal_can_still_be_cancelled_or_superseded() {
    let mut l = running();
    l.await_approval("g1").unwrap();
    l.cancel("g1", "no longer needed").unwrap();
    assert!(matches!(l.state("g1"), Some(GoalState::Cancelled { .. })));

    let mut l2 = running();
    l2.await_approval("g1").unwrap();
    l2.supersede("g1", "g1-rev2").unwrap();
    assert!(matches!(l2.state("g1"), Some(GoalState::Superseded { .. })));
}

#[test]
fn an_approval_landing_after_cancellation_cannot_revive_the_goal() {
    let mut l = running();
    l.await_approval("g1").unwrap();
    l.cancel("g1", "operator changed their mind").unwrap();

    assert!(
        matches!(l.approve("g1"), Err(TransitionDenied::AlreadyTerminal { .. })),
        "a late approval must not undo a cancellation"
    );
}

#[test]
fn transitions_on_an_unknown_goal_are_refused_not_silently_created() {
    let mut l = Lifecycle::new();

    assert_eq!(l.cancel("ghost", "x"), Err(TransitionDenied::UnknownGoal));
    assert_eq!(l.complete("ghost"), Err(TransitionDenied::UnknownGoal));
    assert_eq!(l.await_approval("ghost"), Err(TransitionDenied::UnknownGoal));
    assert_eq!(l.state("ghost"), None, "a refused transition must not conjure the goal into being");
}

#[test]
fn completed_and_failed_are_terminal_as_well() {
    let mut done = running();
    done.complete("g1").unwrap();
    assert!(matches!(done.cancel("g1", "late"), Err(TransitionDenied::AlreadyTerminal { .. })));

    let mut failed = running();
    failed.fail("g1", "compile error").unwrap();
    assert!(matches!(failed.complete("g1"), Err(TransitionDenied::AlreadyTerminal { .. })));
    assert!(!failed.should_execute("g1"));
}

#[test]
fn live_and_terminal_goals_partition_the_tracked_set() {
    let mut l = Lifecycle::new();
    l.admit("running");
    l.admit("parked");
    l.admit("cancelled");
    l.admit("done");

    l.await_approval("parked").unwrap();
    l.cancel("cancelled", "stop").unwrap();
    l.complete("done").unwrap();

    let live = l.live_goals();
    let terminal = l.terminal_goals();

    assert_eq!(live, vec!["parked", "running"], "parked is live: it is waiting, not finished");
    assert_eq!(terminal, vec!["cancelled", "done"]);
    assert_eq!(live.len() + terminal.len(), 4, "every tracked goal is in exactly one bucket");
}
