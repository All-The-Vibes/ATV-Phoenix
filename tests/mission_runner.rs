use std::cell::RefCell;
use std::collections::BTreeMap;

use phoenix::budget::Limits;
use phoenix::execution_backend::{BackendOutcome, ExecutionBackend, Job};
use phoenix::mission::{MissionGoal, MissionRunner};

#[derive(Default)]
struct ScriptedBackend {
    failures: BTreeMap<String, String>,
    calls: RefCell<Vec<String>>,
}

impl ScriptedBackend {
    fn with_failure(mut self, goal: &str, reason: &str) -> Self {
        self.failures.insert(goal.to_string(), reason.to_string());
        self
    }

    fn calls(&self) -> Vec<String> {
        self.calls.borrow().clone()
    }
}

impl ExecutionBackend for ScriptedBackend {
    fn name(&self) -> &str {
        "scripted"
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        self.calls.borrow_mut().push(job.id.clone());
        if let Some(reason) = self.failures.get(&job.id) {
            return BackendOutcome::failed(job.id.clone(), self.name(), reason.clone());
        }
        BackendOutcome::completed(job.id.clone(), self.name(), format!("ran {}", job.task))
    }
}

fn goal(id: &str, prerequisites: &[&str], token_cost: u64) -> MissionGoal {
    MissionGoal::new(
        id,
        format!("task-{id}"),
        prerequisites.iter().map(|p| p.to_string()).collect(),
        token_cost,
    )
}

#[test]
fn a_mission_over_a_diamond_dag_completes_in_dependency_order() {
    let tmp = tempfile::tempdir().unwrap();
    let goals = vec![
        goal("a", &[], 1),
        goal("b", &["a"], 1),
        goal("c", &["a"], 1),
        goal("d", &["b", "c"], 1),
    ];
    let mut runner = MissionRunner::new(
        tmp.path(),
        tmp.path().join("worktrees"),
        goals,
        1,
        Limits::unlimited(),
        Limits::unlimited(),
    )
    .unwrap();

    let report = runner.run(&ScriptedBackend::default()).unwrap();

    assert!(report.settled);
    assert_eq!(report.completion_order, vec!["a", "b", "c", "d"]);
}

#[test]
fn bounded_concurrency_is_never_exceeded() {
    let tmp = tempfile::tempdir().unwrap();
    let goals = vec![
        goal("g1", &[], 1),
        goal("g2", &[], 1),
        goal("g3", &[], 1),
        goal("g4", &[], 1),
    ];
    let mut runner = MissionRunner::new(
        tmp.path(),
        tmp.path().join("worktrees"),
        goals,
        2,
        Limits::unlimited(),
        Limits::unlimited(),
    )
    .unwrap();

    let report = runner.run(&ScriptedBackend::default()).unwrap();

    assert!(report.settled);
    assert!(
        report.max_in_flight <= 2,
        "max in-flight was {}",
        report.max_in_flight
    );
    assert_eq!(report.max_in_flight, 2);
}

#[test]
fn failed_goal_blocks_only_its_subtree_while_unrelated_branch_finishes() {
    let tmp = tempfile::tempdir().unwrap();
    let goals = vec![goal("a", &[], 1), goal("b", &["a"], 1), goal("x", &[], 1)];
    let backend = ScriptedBackend::default().with_failure("a", "boom");
    let mut runner = MissionRunner::new(
        tmp.path(),
        tmp.path().join("worktrees"),
        goals,
        2,
        Limits::unlimited(),
        Limits::unlimited(),
    )
    .unwrap();

    let report = runner.run(&backend).unwrap();

    assert!(report.settled);
    assert!(report.failed.contains(&"a".to_string()));
    assert!(report.blocked.contains(&"b".to_string()));
    assert!(report.completion_order.contains(&"x".to_string()));
    assert_eq!(
        backend.calls(),
        vec!["a", "x"],
        "blocked goals must never execute"
    );
}

#[test]
fn every_executed_goal_had_a_lease_and_worktree_assignment_when_it_ran() {
    let tmp = tempfile::tempdir().unwrap();
    let goals = vec![goal("g1", &[], 1), goal("g2", &[], 1)];
    let mut runner = MissionRunner::new(
        tmp.path(),
        tmp.path().join("worktrees"),
        goals,
        2,
        Limits::unlimited(),
        Limits::unlimited(),
    )
    .unwrap();

    let report = runner.run(&ScriptedBackend::default()).unwrap();

    assert!(!report.executed.is_empty());
    assert!(
        report
            .executed
            .iter()
            .all(|e| e.held_lease && e.held_worktree),
        "every execution record must prove both lease+worktree ownership: {:?}",
        report.executed
    );
}

#[test]
fn mission_budget_exhaustion_stops_mission_while_goal_budget_exhaustion_stops_only_that_goal() {
    let tmp_mission = tempfile::tempdir().unwrap();
    let mut mission_stop_runner = MissionRunner::new(
        tmp_mission.path(),
        tmp_mission.path().join("worktrees"),
        vec![goal("a", &[], 2), goal("b", &[], 2)],
        2,
        Limits::unlimited().with_tokens(3),
        Limits::unlimited().with_tokens(10),
    )
    .unwrap();
    let mission_stop = mission_stop_runner
        .run(&ScriptedBackend::default())
        .unwrap();

    assert!(mission_stop.mission_budget_exhausted);
    assert!(
        mission_stop.failed.contains(&"a".to_string())
            || mission_stop.failed.contains(&"b".to_string())
    );
    assert!(
        mission_stop.executed.len() <= 1,
        "mission stop should prevent later executions"
    );

    let tmp_goal = tempfile::tempdir().unwrap();
    let mut goal_stop_runner = MissionRunner::new(
        tmp_goal.path(),
        tmp_goal.path().join("worktrees"),
        vec![goal("a", &[], 2), goal("b", &["a"], 1), goal("x", &[], 1)],
        2,
        Limits::unlimited().with_tokens(10),
        Limits::unlimited().with_tokens(1),
    )
    .unwrap();
    let goal_stop = goal_stop_runner.run(&ScriptedBackend::default()).unwrap();

    assert!(!goal_stop.mission_budget_exhausted);
    assert!(goal_stop.failed.contains(&"a".to_string()));
    assert!(goal_stop.blocked.contains(&"b".to_string()));
    assert!(goal_stop.completion_order.contains(&"x".to_string()));
}

#[test]
fn run_ledger_records_one_entry_per_executed_goal_and_goal_traces_verify_independently() {
    let tmp = tempfile::tempdir().unwrap();
    let goals = vec![
        goal("g1", &[], 1),
        goal("g2", &[], 1),
        goal("g3", &["g1"], 1),
    ];
    let mut runner = MissionRunner::new(
        tmp.path(),
        tmp.path().join("worktrees"),
        goals,
        2,
        Limits::unlimited(),
        Limits::unlimited(),
    )
    .unwrap();

    let report = runner.run(&ScriptedBackend::default()).unwrap();
    let ledger = runner.ledger_read();
    let verify = runner.verify_traces();

    assert_eq!(
        ledger.entries.len(),
        report.executed.len(),
        "one ledger row per executed goal"
    );
    assert!(ledger.is_intact());
    assert!(verify.all_ok(), "every chain should verify independently");
    assert!(verify.supervisor_intact());
}
