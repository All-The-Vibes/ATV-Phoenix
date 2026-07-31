use std::cell::RefCell;
use std::collections::BTreeSet;

use phoenix::budget::Limits;
use phoenix::execution_backend::{BackendOutcome, ExecutionBackend, Job};
use phoenix::mission::{MissionConfig, MissionGoal, MissionRunner};
use tempfile::TempDir;

#[derive(Default)]
struct ScriptedBackend {
    fail_goals: BTreeSet<String>,
    in_execute: RefCell<usize>,
    peak_in_execute: RefCell<usize>,
    order: RefCell<Vec<String>>,
}

impl ScriptedBackend {
    fn failing(goals: &[&str]) -> Self {
        Self {
            fail_goals: goals.iter().map(|g| (*g).to_string()).collect(),
            ..Self::default()
        }
    }

    fn peak_in_execute(&self) -> usize {
        *self.peak_in_execute.borrow()
    }
}

impl ExecutionBackend for ScriptedBackend {
    fn name(&self) -> &str {
        "scripted"
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        {
            let mut active = self.in_execute.borrow_mut();
            *active += 1;
            let mut peak = self.peak_in_execute.borrow_mut();
            *peak = (*peak).max(*active);
        }
        self.order.borrow_mut().push(job.id.clone());
        let outcome = if self.fail_goals.contains(&job.id) {
            BackendOutcome::failed(&job.id, self.name(), format!("{} failed", job.id))
        } else {
            BackendOutcome::completed(&job.id, self.name(), format!("{} completed", job.id))
        };
        *self.in_execute.borrow_mut() -= 1;
        outcome
    }
}

fn cfg(dir: &TempDir, concurrency: usize, mission_limits: Limits, goal_limits: Limits) -> MissionConfig {
    let mut cfg = MissionConfig::in_dir(dir.path());
    cfg.concurrency = concurrency;
    cfg.mission_limits = mission_limits;
    cfg.goal_limits = goal_limits;
    cfg
}

fn idx(order: &[String], goal: &str) -> usize {
    order.iter().position(|g| g == goal).expect("goal should be in execution order")
}

#[test]
fn mission_runner_executes_a_diamond_in_dependency_order_with_bounded_concurrency() {
    let dir = TempDir::new().unwrap();
    let goals = vec![
        MissionGoal::new("a", "a", vec![]),
        MissionGoal::new("b", "b", vec!["a".into()]),
        MissionGoal::new("c", "c", vec!["a".into()]),
        MissionGoal::new("d", "d", vec!["b".into(), "c".into()]),
    ];
    let mut runner = MissionRunner::new(
        goals,
        cfg(&dir, 2, Limits::unlimited().with_tokens(100), Limits::unlimited().with_tokens(100)),
    )
    .unwrap();

    let backend = ScriptedBackend::default();
    let report = runner.run(&backend);

    assert!(report.settled);
    assert_eq!(report.execution_order.len(), 4);
    assert!(idx(&report.execution_order, "a") < idx(&report.execution_order, "b"));
    assert!(idx(&report.execution_order, "a") < idx(&report.execution_order, "c"));
    assert!(idx(&report.execution_order, "b") < idx(&report.execution_order, "d"));
    assert!(idx(&report.execution_order, "c") < idx(&report.execution_order, "d"));

    assert!(report.peak_in_flight <= 2, "supervisor bound must hold");
    assert!(backend.peak_in_execute() <= 1, "injected backend stays deterministic in tests");

    assert!(report.execution_records.iter().all(|r| r.had_valid_lease && r.had_worktree_assignment));
    assert_eq!(report.ledger.entries.len(), report.execution_order.len());
    assert!(report.traces.all_ok());
    assert!(report.traces.goals.iter().all(|g| g.ok));
    for goal in &report.execution_order {
        let status = report.traces.goals.iter().find(|g| g.writer == *goal).unwrap();
        assert!(status.rows > 0, "executed goal {goal} should have trace rows");
    }
}

#[test]
fn mission_runner_contains_failures_to_the_failed_subtree() {
    let dir = TempDir::new().unwrap();
    let goals = vec![
        MissionGoal::new("root", "root", vec![]),
        MissionGoal::new("left", "left", vec!["root".into()]),
        MissionGoal::new("left-child", "left-child", vec!["left".into()]),
        MissionGoal::new("right", "right", vec!["root".into()]),
    ];
    let mut runner = MissionRunner::new(
        goals,
        cfg(&dir, 2, Limits::unlimited().with_tokens(100), Limits::unlimited().with_tokens(100)),
    )
    .unwrap();

    let backend = ScriptedBackend::failing(&["left"]);
    let report = runner.run(&backend);

    assert!(report.settled);
    assert!(report.execution_order.contains(&"right".to_string()));
    assert!(!report.execution_order.contains(&"left-child".to_string()));
    assert!(report.failed.contains(&"left".to_string()));
    assert!(report.blocked.contains(&"left-child".to_string()));
}

#[test]
fn goal_budget_exhaustion_stops_only_that_goal() {
    let dir = TempDir::new().unwrap();
    let goals = vec![
        MissionGoal::new("expensive", "expensive", vec![]).with_budget_tokens(5),
        MissionGoal::new("cheap", "cheap", vec![]).with_budget_tokens(1),
    ];
    let mut runner = MissionRunner::new(
        goals,
        cfg(&dir, 1, Limits::unlimited().with_tokens(100), Limits::unlimited().with_tokens(3)),
    )
    .unwrap();

    let backend = ScriptedBackend::default();
    let report = runner.run(&backend);

    assert!(!report.mission_budget_exhausted);
    assert!(report.goal_budget_exhausted.contains(&"expensive".to_string()));
    assert!(report.failed.contains(&"expensive".to_string()));
    assert!(report.execution_order.contains(&"cheap".to_string()));
    assert!(!report.execution_order.contains(&"expensive".to_string()));
    assert!(report.settled);
}

#[test]
fn mission_budget_exhaustion_stops_the_mission() {
    let dir = TempDir::new().unwrap();
    let goals = vec![
        MissionGoal::new("g1", "g1", vec![]).with_budget_tokens(2),
        MissionGoal::new("g2", "g2", vec![]).with_budget_tokens(2),
    ];
    let mut runner = MissionRunner::new(
        goals,
        cfg(&dir, 1, Limits::unlimited().with_tokens(3), Limits::unlimited().with_tokens(10)),
    )
    .unwrap();

    let backend = ScriptedBackend::default();
    let report = runner.run(&backend);

    assert!(report.mission_budget_exhausted);
    assert_eq!(report.execution_order.len(), 1, "mission stop should prevent later executions");
    assert_eq!(report.ledger.entries.len(), 1, "run ledger tracks only executed goals");
    assert!(report.failed.contains(&"g2".to_string()));
}
