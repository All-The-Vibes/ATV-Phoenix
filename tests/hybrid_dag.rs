//! Dependency-aware readiness with contained failure (issue #82).
//!
//! Named test target on purpose: `cargo test --test hybrid_dag` fails hard (exit 101) when the
//! target is absent, so this gate cannot pass vacuously the way a name *filter* would.

use phoenix::hybrid_dag::{DagDenied, GoalDag, GoalOutcome};

/// `a -> b -> c` plus an unrelated `x`.
fn mission() -> GoalDag {
    let mut dag = GoalDag::new();
    dag.add_goal("a", &[]).unwrap();
    dag.add_goal("b", &["a"]).unwrap();
    dag.add_goal("c", &["b"]).unwrap();
    dag.add_goal("x", &[]).unwrap();
    dag
}

#[test]
fn ready_lists_only_roots_before_anything_has_run() {
    let dag = mission();
    assert_eq!(dag.ready(), vec!["a".to_string(), "x".to_string()]);
    assert!(!dag.is_settled());
}

#[test]
fn a_goal_is_not_ready_while_a_prerequisite_is_still_pending() {
    let dag = mission();
    assert!(!dag.ready().contains(&"b".to_string()), "`a` has not succeeded yet");
}

#[test]
fn success_releases_exactly_the_next_layer() {
    let mut dag = mission();
    dag.mark_succeeded("a").unwrap();
    assert_eq!(dag.ready(), vec!["b".to_string(), "x".to_string()]);
    assert!(!dag.ready().contains(&"c".to_string()), "`b` has not succeeded yet");
}

#[test]
fn a_failed_prerequisite_blocks_its_dependents_transitively() {
    let mut dag = mission();
    let blocked = dag.mark_failed("a").unwrap();
    assert_eq!(blocked, vec!["b".to_string(), "c".to_string()], "the grandchild is blocked too");
    assert_eq!(dag.state("b"), Some(GoalOutcome::Blocked));
    assert_eq!(dag.state("c"), Some(GoalOutcome::Blocked));
}

#[test]
fn an_unrelated_branch_keeps_running_when_another_branch_fails() {
    let mut dag = mission();
    dag.mark_failed("a").unwrap();
    assert_eq!(dag.ready(), vec!["x".to_string()], "containment: `x` never depended on `a`");
    assert_eq!(dag.state("x"), Some(GoalOutcome::Pending));
    dag.mark_succeeded("x").unwrap();
    assert!(dag.is_settled(), "mission concludes with one branch done and one contained");
}

#[test]
fn blocked_is_not_failed() {
    let mut dag = mission();
    dag.mark_failed("a").unwrap();
    assert_eq!(dag.failed(), vec!["a".to_string()], "only `a` actually ran and failed");
    assert_eq!(dag.blocked(), vec!["b".to_string(), "c".to_string()], "these never ran");
}

#[test]
fn a_blocked_goal_can_never_be_resurrected() {
    let mut dag = mission();
    dag.mark_failed("a").unwrap();
    let denied = dag.mark_succeeded("b").unwrap_err();
    assert_eq!(
        denied,
        DagDenied::AlreadyResolved { goal: "b".into(), state: GoalOutcome::Blocked },
        "a late-arriving success must not revive a contained goal"
    );
    assert_eq!(dag.state("b"), Some(GoalOutcome::Blocked));
}

#[test]
fn success_out_of_dependency_order_is_refused() {
    let mut dag = mission();
    let denied = dag.mark_succeeded("b").unwrap_err();
    assert_eq!(
        denied,
        DagDenied::NotReady { goal: "b".into(), prerequisite: "a".into() },
        "a result computed before its prerequisite landed is stale, not done"
    );
    assert_eq!(dag.state("b"), Some(GoalOutcome::Pending), "a refused claim records nothing");
}

#[test]
fn resolving_a_goal_twice_is_refused() {
    let mut dag = mission();
    dag.mark_succeeded("a").unwrap();
    assert_eq!(
        dag.mark_failed("a").unwrap_err(),
        DagDenied::AlreadyResolved { goal: "a".into(), state: GoalOutcome::Succeeded }
    );
}

#[test]
fn an_unknown_prerequisite_is_refused_not_treated_as_satisfied() {
    let mut dag = GoalDag::new();
    let denied = dag.add_goal("b", &["ghost"]).unwrap_err();
    assert_eq!(
        denied,
        DagDenied::UnknownPrerequisite { goal: "b".into(), prerequisite: "ghost".into() }
    );
    assert!(dag.ready().is_empty(), "the refused goal was not admitted");
}

#[test]
fn a_cycle_is_unrepresentable_because_prerequisites_must_predate_dependents() {
    let mut dag = GoalDag::new();
    dag.add_goal("a", &[]).unwrap();
    dag.add_goal("b", &["a"]).unwrap();
    // Closing the loop would need `a` to depend on `b`, but `a` is already declared.
    assert_eq!(
        dag.add_goal("a", &["b"]).unwrap_err(),
        DagDenied::DuplicateGoal { goal: "a".into() }
    );
    assert_eq!(dag.add_goal("c", &["c"]).unwrap_err(), DagDenied::SelfDependency { goal: "c".into() });
}

#[test]
fn unknown_goals_are_refused_rather_than_conjured() {
    let mut dag = GoalDag::new();
    assert_eq!(dag.mark_succeeded("nope").unwrap_err(), DagDenied::UnknownGoal { goal: "nope".into() });
    assert_eq!(dag.mark_failed("nope").unwrap_err(), DagDenied::UnknownGoal { goal: "nope".into() });
}

#[test]
fn a_second_failure_reports_only_the_goals_it_newly_blocked() {
    let mut dag = GoalDag::new();
    dag.add_goal("a", &[]).unwrap();
    dag.add_goal("p", &[]).unwrap();
    dag.add_goal("shared", &["a", "p"]).unwrap();

    assert_eq!(dag.mark_failed("a").unwrap(), vec!["shared".to_string()]);
    assert_eq!(
        dag.mark_failed("p").unwrap(),
        Vec::<String>::new(),
        "`shared` was already blocked; reporting it twice would double-count the damage"
    );
    assert_eq!(dag.blocked(), vec!["shared".to_string()]);
}

#[test]
fn a_goal_needs_all_of_its_prerequisites_not_just_one() {
    let mut dag = GoalDag::new();
    dag.add_goal("a", &[]).unwrap();
    dag.add_goal("p", &[]).unwrap();
    dag.add_goal("shared", &["a", "p"]).unwrap();

    dag.mark_succeeded("a").unwrap();
    assert_eq!(dag.ready(), vec!["p".to_string()], "`shared` still waits on `p`");
    dag.mark_succeeded("p").unwrap();
    assert_eq!(dag.ready(), vec!["shared".to_string()]);
}

#[test]
fn ready_order_is_declaration_order_and_stable() {
    let mut dag = GoalDag::new();
    for id in ["z", "m", "a"] {
        dag.add_goal(id, &[]).unwrap();
    }
    let first = dag.ready();
    assert_eq!(first, vec!["z".to_string(), "m".to_string(), "a".to_string()]);
    assert_eq!(dag.ready(), first, "a pure query must not depend on call count");
}

#[test]
fn terminal_states_report_themselves_as_terminal() {
    assert!(!GoalOutcome::Pending.is_terminal());
    for s in [GoalOutcome::Succeeded, GoalOutcome::Failed, GoalOutcome::Blocked] {
        assert!(s.is_terminal());
    }
}
