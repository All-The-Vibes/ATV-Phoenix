//! Dependency-aware readiness with contained failure (issue #82).
//!
//! Named test target on purpose: `cargo test --test hybrid_dag` fails hard (exit 101) when the
//! target is absent, so this gate cannot pass vacuously the way a name *filter* would.

use std::collections::BTreeMap;

use phoenix::hybrid_dag::{
    DagDenied, GoalBackend, GoalDag, GoalOutcome, HybridDenied, HybridMission, IntegrationFailure,
    IntegrationWorker, INTEGRATION_WORKTREE,
};

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

#[derive(Default)]
struct ScriptedIntegration {
    merges: Vec<(String, String, String)>,
    outcomes: BTreeMap<String, Result<(), IntegrationFailure>>,
}

impl ScriptedIntegration {
    fn conflict_on(mut self, goal: &str) -> Self {
        self.outcomes.insert(
            goal.to_string(),
            Err(IntegrationFailure::Conflict { detail: format!("{goal} conflicts") }),
        );
        self
    }
}

impl IntegrationWorker for ScriptedIntegration {
    fn merge(&mut self, worktree: &str, goal: &str, branch: &str) -> Result<(), IntegrationFailure> {
        self.merges.push((worktree.to_string(), goal.to_string(), branch.to_string()));
        self.outcomes.remove(goal).unwrap_or(Ok(()))
    }
}

fn mixed_mission() -> HybridMission {
    let mut mission = HybridMission::new(1, 5);
    mission.add_goal("a", &[]).unwrap();
    mission.add_goal("x", &[]).unwrap();
    mission.add_goal("b", &["a"]).unwrap();
    mission
}

#[test]
fn ready_goals_dispatch_concurrently_across_local_and_cloud() {
    let mut mission = mixed_mission();
    let dispatches = mission.dispatch_ready(0);

    assert_eq!(dispatches.len(), 2, "both independent roots dispatch in one scheduling step");
    assert_eq!(dispatches[0].goal, "a");
    assert_eq!(dispatches[0].backend, GoalBackend::Local);
    assert_eq!(dispatches[1].goal, "x");
    assert_eq!(dispatches[1].backend, GoalBackend::CopilotCloud);
}

#[test]
fn cloud_sla_expiry_advances_fencing_and_falls_back_without_halting_other_work() {
    let mut mission = mixed_mission();
    let dispatches = mission.dispatch_ready(0);
    let cloud = dispatches
        .iter()
        .find(|d| d.backend == GoalBackend::CopilotCloud)
        .expect("one root should overflow to cloud");
    let old_token = cloud.token;

    // Time has passed the cloud queue SLA.
    let retry = mission.expire_cloud_goal(&cloud.goal, 5).unwrap().expect("expired cloud goal must be re-dispatched");
    assert!(retry.token > old_token, "fence token must advance on fallback/re-dispatch");
}

#[test]
fn stale_cloud_result_is_rejected_without_merging() {
    let mut mission = mixed_mission();
    let dispatches = mission.dispatch_ready(0);
    let cloud = dispatches
        .iter()
        .find(|d| d.backend == GoalBackend::CopilotCloud)
        .expect("one root should overflow to cloud")
        .clone();
    let fresh = mission.expire_cloud_goal(&cloud.goal, 5).unwrap().expect("expired cloud goal must be re-dispatched");

    let mut integration = ScriptedIntegration::default();
    let denied = mission
        .report_success(
            &cloud.goal,
            GoalBackend::CopilotCloud,
            cloud.token,
            "copilot/stale",
            6,
            &mut integration,
        )
        .unwrap_err();
    assert_eq!(denied, HybridDenied::StaleResult { goal: cloud.goal.clone(), token: cloud.token });
    assert!(
        integration.merges.is_empty(),
        "stale branch must be fenced out before integration is attempted"
    );

    mission
        .report_success(
            &fresh.goal,
            fresh.backend,
            fresh.token,
            "copilot/fresh",
            6,
            &mut integration,
        )
        .unwrap();
}

#[test]
fn integration_merges_only_proven_goals_in_dependency_order_using_dedicated_worktree() {
    let mut mission = mixed_mission();
    let dispatches = mission.dispatch_ready(0);
    let local = dispatches
        .iter()
        .find(|d| d.backend == GoalBackend::Local)
        .expect("local root")
        .clone();
    let cloud = dispatches
        .iter()
        .find(|d| d.backend == GoalBackend::CopilotCloud)
        .expect("cloud root")
        .clone();
    let mut integration = ScriptedIntegration::default();

    // Cloud root proves first; dependent `b` is still blocked on `a`.
    mission
        .report_success(
            &cloud.goal,
            cloud.backend,
            cloud.token,
            "copilot/x",
            1,
            &mut integration,
        )
        .unwrap();
    // Local root proves next; now `b` can dispatch.
    mission
        .report_success(&local.goal, local.backend, local.token, "local/a", 1, &mut integration)
        .unwrap();

    let b = mission
        .dispatch_ready(2)
        .into_iter()
        .find(|d| d.goal == "b")
        .expect("dependent should dispatch after prerequisite integrates");
    mission
        .report_success(&b.goal, b.backend, b.token, "local/b", 3, &mut integration)
        .unwrap();

    assert_eq!(
        integration.merges,
        vec![
            (INTEGRATION_WORKTREE.to_string(), "x".to_string(), "copilot/x".to_string()),
            (INTEGRATION_WORKTREE.to_string(), "a".to_string(), "local/a".to_string()),
            (INTEGRATION_WORKTREE.to_string(), "b".to_string(), "local/b".to_string()),
        ],
        "every proven branch must merge only through the dedicated integration worktree"
    );
}

#[test]
fn merge_conflicts_surface_as_explicit_failures_and_block_dependents_while_unrelated_branches_continue() {
    let mut mission = HybridMission::new(1, 5);
    mission.add_goal("a", &[]).unwrap();
    mission.add_goal("b", &["a"]).unwrap();
    mission.add_goal("x", &[]).unwrap();

    let dispatches = mission.dispatch_ready(0);
    let a = dispatches.iter().find(|d| d.goal == "a").unwrap().clone();
    let x = dispatches.iter().find(|d| d.goal == "x").unwrap().clone();
    let mut integration = ScriptedIntegration::default().conflict_on("a");

    mission
        .report_success(&a.goal, a.backend, a.token, "branch/a", 1, &mut integration)
        .unwrap();
    assert_eq!(mission.state("a"), Some(GoalOutcome::Failed), "conflict should fail the goal");
    assert_eq!(mission.state("b"), Some(GoalOutcome::Blocked), "dependent must be blocked");
    assert!(
        mission
            .failure_reason("a")
            .expect("failure reason")
            .contains("merge conflict"),
        "conflict must surface as an explicit failure"
    );

    // Unrelated root still progresses.
    mission
        .report_success(&x.goal, x.backend, x.token, "branch/x", 1, &mut integration)
        .unwrap();
    assert_eq!(mission.state("x"), Some(GoalOutcome::Succeeded));
}
