//! Acceptance tests for the mission composition root (`src/mission.rs`).
//!
//! Done-check: `cargo test --locked --test mission_runner`
//!
//! Six properties are pinned here, each as its own test:
//!
//! 1. A diamond DAG completes in dependency order.
//! 2. Bounded concurrency is never exceeded.
//! 3. A failed goal blocks only its own subtree; the unrelated branch still finishes.
//! 4. Every executed goal held BOTH a lease and a worktree assignment at execution time.
//! 5. Mission-level budget exhaustion stops the mission; goal-level stops only that goal.
//! 6. The run ledger records one entry per executed goal AND each goal trace chain verifies.

use std::collections::HashSet;
use std::sync::{Arc, Mutex};

use phoenix::budget::Limits;
use phoenix::execution_backend::{BackendOutcome, ExecutionBackend, Job, PreflightOutcome};
use phoenix::hybrid_dag::GoalOutcome;
use phoenix::mission::{run_mission, MissionConfig};
use phoenix::run_ledger::RunLedger;
use tempfile::TempDir;

// ── Test backends ─────────────────────────────────────────────────────────────────────────────────

/// Succeeds for every job unconditionally.
struct AlwaysSucceeds;

impl ExecutionBackend for AlwaysSucceeds {
    fn name(&self) -> &str {
        "test-always-succeeds"
    }
    fn preflight(&self, _job: &Job) -> PreflightOutcome {
        PreflightOutcome::eligible()
    }
    fn execute(&self, job: &Job) -> BackendOutcome {
        BackendOutcome::completed(&job.id, self.name(), "ok")
    }
}

/// Fails every job whose id is in the configured set; succeeds all others.
struct FailGoals {
    failing: HashSet<String>,
}

impl FailGoals {
    fn new(failing: &[&str]) -> Self {
        Self { failing: failing.iter().map(|s| s.to_string()).collect() }
    }
}

impl ExecutionBackend for FailGoals {
    fn name(&self) -> &str {
        "test-fail-goals"
    }
    fn preflight(&self, _job: &Job) -> PreflightOutcome {
        PreflightOutcome::eligible()
    }
    fn execute(&self, job: &Job) -> BackendOutcome {
        if self.failing.contains(&job.id) {
            BackendOutcome::failed(&job.id, self.name(), "injected failure")
        } else {
            BackendOutcome::completed(&job.id, self.name(), "ok")
        }
    }
}

/// Records the order in which goals are executed so tests can assert dependency ordering.
struct OrderRecorder {
    log: Arc<Mutex<Vec<String>>>,
}

impl OrderRecorder {
    fn new(log: Arc<Mutex<Vec<String>>>) -> Self {
        Self { log }
    }
}

impl ExecutionBackend for OrderRecorder {
    fn name(&self) -> &str {
        "test-order-recorder"
    }
    fn preflight(&self, _job: &Job) -> PreflightOutcome {
        PreflightOutcome::eligible()
    }
    fn execute(&self, job: &Job) -> BackendOutcome {
        self.log.lock().unwrap().push(job.id.clone());
        BackendOutcome::completed(&job.id, self.name(), "ok")
    }
}

// ── Test 1: diamond DAG completes in dependency order ────────────────────────────────────────────

#[test]
fn diamond_dag_completes_in_dependency_order() {
    //        a
    //       / \
    //      b   c
    //       \ /
    //        d
    //
    // a must run before b and c; b and c must both run before d.
    let ws = TempDir::new().unwrap();
    let log = Arc::new(Mutex::new(Vec::new()));
    let backend = OrderRecorder::new(Arc::clone(&log));

    let goals: &[(&str, &[&str])] = &[
        ("a", &[]),
        ("b", &["a"]),
        ("c", &["a"]),
        ("d", &["b", "c"]),
    ];

    let report = run_mission(goals, MissionConfig::new(4), ws.path(), &backend);

    assert!(report.settled, "mission must settle");

    let order = log.lock().unwrap().clone();
    assert_eq!(order.len(), 4, "all four goals must execute");

    // a must precede b and c
    let pos = |g: &str| order.iter().position(|x| x == g).unwrap();
    assert!(pos("a") < pos("b"), "a must run before b");
    assert!(pos("a") < pos("c"), "a must run before c");
    // b and c must both precede d
    assert!(pos("b") < pos("d"), "b must run before d");
    assert!(pos("c") < pos("d"), "c must run before d");

    // Every goal should have succeeded
    let all_goals = ["a", "b", "c", "d"];
    for g in all_goals {
        let rec = report.records.iter().find(|r| r.goal == g).unwrap();
        assert_eq!(rec.outcome, GoalOutcome::Succeeded, "{g} should have succeeded");
    }
}

// ── Test 2: bounded concurrency is never exceeded ─────────────────────────────────────────────────

#[test]
fn bounded_concurrency_is_never_exceeded() {
    // Four independent goals with capacity = 1: only one may ever be in-flight at a time.
    let ws = TempDir::new().unwrap();
    let goals: &[(&str, &[&str])] =
        &[("a", &[]), ("b", &[]), ("c", &[]), ("d", &[])];

    let report = run_mission(goals, MissionConfig::new(1), ws.path(), &AlwaysSucceeds);

    assert!(report.settled, "mission must settle");
    assert!(
        report.peak_concurrency <= 1,
        "peak concurrency {} exceeded capacity 1",
        report.peak_concurrency
    );

    // Verify with a larger capacity too — peak must stay ≤ capacity.
    let ws2 = TempDir::new().unwrap();
    let report2 = run_mission(goals, MissionConfig::new(2), ws2.path(), &AlwaysSucceeds);

    assert!(
        report2.peak_concurrency <= 2,
        "peak concurrency {} exceeded capacity 2",
        report2.peak_concurrency
    );
}

// ── Test 3: a failed goal blocks only its subtree; unrelated branch still finishes ───────────────

#[test]
fn failed_goal_blocks_only_its_subtree_unrelated_branch_completes() {
    //    a (succeeds)      b (FAILS)
    //    |                 |
    //    c (should run)    d (should be blocked)
    //
    // a and b are independent roots. c depends on a (should succeed). d depends on b (should be
    // blocked). The mission must settle despite b failing and d being blocked.
    let ws = TempDir::new().unwrap();

    let goals: &[(&str, &[&str])] = &[
        ("a", &[]),
        ("b", &[]),
        ("c", &["a"]),
        ("d", &["b"]),
    ];

    let report = run_mission(goals, MissionConfig::new(4), ws.path(), &FailGoals::new(&["b"]));

    assert!(report.settled, "the mission must settle even when a branch fails");

    // The unrelated branch (a → c) must run to completion.
    let rec_c = report.records.iter().find(|r| r.goal == "c");
    assert!(
        matches!(rec_c, Some(r) if r.outcome == GoalOutcome::Succeeded),
        "c should have succeeded (its ancestor a succeeded); got {:?}",
        rec_c
    );

    // b failed.
    let rec_b = report.records.iter().find(|r| r.goal == "b").unwrap();
    assert_eq!(rec_b.outcome, GoalOutcome::Failed, "b must be recorded as failed");

    // d must be blocked — it never executed.
    assert!(
        report.records.iter().all(|r| r.goal != "d"),
        "d must not appear in execution records — it was blocked, not executed"
    );
}

// ── Test 4: every executed goal held both a lease and a worktree at execution time ───────────────

#[test]
fn every_executed_goal_held_lease_and_worktree_at_execution_time() {
    // Four goals in a chain so each one exercises the isolation snapshot after the previous one
    // released its resources.
    let ws = TempDir::new().unwrap();

    let goals: &[(&str, &[&str])] = &[
        ("a", &[]),
        ("b", &["a"]),
        ("c", &["b"]),
        ("d", &["c"]),
    ];

    let report = run_mission(goals, MissionConfig::new(2), ws.path(), &AlwaysSucceeds);

    assert!(report.settled);

    // The central assertion: every goal that reached the backend must have held both resources.
    assert!(
        report.all_executed_held_lease_and_worktree(),
        "at least one executed goal was missing a lease or a worktree at execution time: {:?}",
        report
            .executed_goals()
            .filter(|r| !r.had_lease_at_execution || !r.had_worktree_at_execution)
            .map(|r| (&r.goal, r.had_lease_at_execution, r.had_worktree_at_execution))
            .collect::<Vec<_>>()
    );

    // Also assert each individually so the failure message names the offender.
    for rec in report.executed_goals() {
        assert!(
            rec.had_lease_at_execution,
            "goal '{}' executed without a lease",
            rec.goal
        );
        assert!(
            rec.had_worktree_at_execution,
            "goal '{}' executed without a worktree assignment",
            rec.goal
        );
    }
}

// ── Test 5: budget exhaustion — mission-level stops everything; goal-level stops only that goal ───

#[test]
fn budget_exhaustion_mission_level_stops_mission_goal_level_stops_only_that_goal() {
    // ── Part A: goal-level budget (tokens = 0 per goal) ──────────────────────────────────────
    //
    // Every goal's first charge fails at goal scope. The mission never hits the mission-level
    // limit, so it keeps trying each goal (each one fails on its own). All goals are attempted;
    // no goal propagates its failure to the mission.
    {
        let ws = TempDir::new().unwrap();
        // Two independent goals, goal limit = 0 tokens (first charge always exceeds it).
        let config = MissionConfig::new(2)
            .with_goal_limits(Limits::unlimited().with_tokens(0));

        let goals: &[(&str, &[&str])] = &[("a", &[]), ("b", &[])];
        let report = run_mission(goals, config, ws.path(), &AlwaysSucceeds);

        assert!(
            report.settled,
            "the mission must settle even when every goal fails on its own budget"
        );
        assert!(
            !report.mission_budget_exhausted,
            "goal-level budget refusals must NOT set mission_budget_exhausted"
        );

        // Both goals must have been attempted and budget-refused.
        for g in ["a", "b"] {
            let rec = report.records.iter().find(|r| r.goal == g)
                .unwrap_or_else(|| panic!("{g} must appear in records"));
            assert!(rec.budget_refused, "{g} must be budget-refused, not silently skipped");
            assert_eq!(rec.outcome, GoalOutcome::Failed);
        }
    }

    // ── Part B: mission-level budget (1 token total, 3 sequential goals) ─────────────────────
    //
    // After the first goal consumes the one allowed token, every subsequent goal hits the
    // mission-level limit and the runner halts, leaving the remaining goals untouched.
    {
        let ws = TempDir::new().unwrap();
        // Sequential chain so execution order is deterministic.
        let config = MissionConfig::new(1)
            .with_mission_limits(Limits::unlimited().with_tokens(1));

        let goals: &[(&str, &[&str])] = &[("a", &[]), ("b", &["a"]), ("c", &["b"])];
        let report = run_mission(goals, config, ws.path(), &AlwaysSucceeds);

        assert!(
            report.mission_budget_exhausted,
            "mission-level budget must be flagged when the limit is hit"
        );

        // "a" ran and consumed the budget; "b" hit the mission limit.
        let a_rec = report.records.iter().find(|r| r.goal == "a").unwrap();
        assert_eq!(a_rec.outcome, GoalOutcome::Succeeded, "a must have run before the limit");

        let b_rec = report.records.iter().find(|r| r.goal == "b").unwrap();
        assert!(b_rec.budget_refused, "b must have been refused by the mission-level budget");

        // "c" must never have been reached.
        assert!(
            report.records.iter().all(|r| r.goal != "c"),
            "c must not appear — mission was halted before c could run"
        );
    }
}

// ── Test 6: run ledger has one entry per executed goal AND every goal chain verifies ─────────────

#[test]
fn run_ledger_has_one_entry_per_executed_goal_and_all_goal_chains_verify() {
    //    a
    //   / \
    //  b   c
    //       \
    //        d
    //
    // All four goals succeed. We expect:
    // - 4 ledger entries (one per executed goal)
    // - every goal's trace chain verifies intact
    // - the supervisor's chain verifies intact
    let ws = TempDir::new().unwrap();

    let goals: &[(&str, &[&str])] = &[
        ("a", &[]),
        ("b", &["a"]),
        ("c", &["a"]),
        ("d", &["c"]),
    ];

    let report = run_mission(goals, MissionConfig::new(2), ws.path(), &AlwaysSucceeds);

    assert!(report.settled);

    // ── Run ledger: one entry per executed goal ───────────────────────────────────────────────
    let ledger = RunLedger::at(report.workspace.join("run-ledger.jsonl"));
    let read = ledger.read();

    let executed_count = report.executed_goals().count();
    assert_eq!(
        read.entries.len(),
        executed_count,
        "ledger must record exactly one entry per executed goal; got {} entries for {} executed",
        read.entries.len(),
        executed_count
    );
    assert!(read.is_intact(), "ledger must not contain damaged rows");

    // Each executed goal appears in the ledger exactly once.
    for rec in report.executed_goals() {
        let entries = read.for_goal(&rec.goal);
        assert_eq!(
            entries.len(),
            1,
            "goal '{}' must have exactly one ledger entry, got {}",
            rec.goal,
            entries.len()
        );
    }

    // ── Trace chains: every chain verifies independently ─────────────────────────────────────
    let cv = &report.chain_verify;

    assert!(
        cv.supervisor.ok,
        "supervisor chain must verify intact (broken at {:?})",
        cv.supervisor.broken_at
    );

    for g in &cv.goals {
        assert!(
            g.ok,
            "goal '{}' chain must verify intact (broken at {:?})",
            g.writer,
            g.broken_at
        );
    }

    assert!(
        cv.all_ok(),
        "at least one chain failed verification: {:?}",
        cv.broken_writers()
    );

    // Goals that executed must have a non-empty chain (at least one row was appended).
    for rec in report.executed_goals() {
        let g_status = cv.goals.iter().find(|g| g.writer == rec.goal)
            .unwrap_or_else(|| panic!("chain status missing for goal '{}'", rec.goal));
        assert!(
            g_status.rows >= 1,
            "executed goal '{}' must have at least one row in its chain",
            rec.goal
        );
    }
}
