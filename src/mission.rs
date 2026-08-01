//! `mission` — composition root: assembles the supervisor spine end-to-end.
//!
//! Every spine module is individually proven in its own tests; this module wires them into a
//! runner that can execute a complete mission. The execution backend is injected so the runner is
//! testable without real processes or network.
//!
//! ## Concurrency model
//!
//! The scheduler is synchronous and sequential — one backend call at a time, no threads. The
//! `Supervisor` bounds how many goals are admitted simultaneously; the `LeaseRegistry` fences
//! stale writes; `WorktreeRegistry` guarantees exclusive workspace paths. "Bounded concurrency"
//! here means `supervisor.in_flight()` never exceeds `capacity` at any observed point.
//!
//! ## Admission variants — exhaustive, no wildcard
//!
//! Every arm of `Admission` is matched explicitly: `Admitted`, `Deferred`, and
//! `RefusedZeroCapacity`. A wildcard arm would silently swallow the next variant the type gains,
//! which is exactly the defect that caused PR #122 to break.

use std::path::Path;

use crate::budget::{BudgetLedger, Limits, Scope};
use crate::execution_backend::{BackendStatus, ExecutionBackend, Job};
use crate::hybrid_dag::{GoalDag, GoalOutcome};
use crate::lease::LeaseRegistry;
use crate::lifecycle::Lifecycle;
use crate::reconcile::reconcile;
use crate::run_artifacts::RunArtifacts;
use crate::run_ledger::RunLedger;
use crate::supervisor::{Admission, Supervisor};
use crate::trace_chains::{verify_mission, MissionChains, MissionVerify};
use crate::worktrees::WorktreeRegistry;

/// Configuration for a single mission run.
pub struct MissionConfig {
    /// Maximum number of goals that may be in flight simultaneously.
    pub capacity: usize,
    /// Mission-wide spending limits. Use `Limits::unlimited()` to disable.
    pub mission_limits: Limits,
    /// Per-goal spending limits, applied uniformly to every goal.
    pub goal_limits: Limits,
}

impl MissionConfig {
    /// A mission that runs at most `capacity` goals concurrently, with no spending limits.
    pub fn new(capacity: usize) -> Self {
        Self { capacity, mission_limits: Limits::unlimited(), goal_limits: Limits::unlimited() }
    }

    pub fn with_mission_limits(mut self, limits: Limits) -> Self {
        self.mission_limits = limits;
        self
    }

    pub fn with_goal_limits(mut self, limits: Limits) -> Self {
        self.goal_limits = limits;
        self
    }
}

/// A snapshot of resource state captured at the exact moment `backend.execute` was called.
///
/// Fields are fixed after capture: a test can assert what was true at execution time without
/// guessing about cleanup that may have happened since.
#[derive(Debug, Clone)]
pub struct GoalRecord {
    pub goal: String,
    /// The outcome recorded in the goal graph after execution (or budget refusal).
    pub outcome: GoalOutcome,
    /// True when the goal held an active lease at the instant `execute` was called.
    pub had_lease_at_execution: bool,
    /// True when the goal held a worktree assignment at the instant `execute` was called.
    pub had_worktree_at_execution: bool,
    /// True when the goal was stopped by a budget check and never reached `execute`.
    pub budget_refused: bool,
}

/// What the runner found when the mission settled (or was forced to stop).
#[derive(Debug)]
pub struct MissionReport {
    /// True when every goal in the graph reached a terminal state.
    pub settled: bool,
    /// One record per goal that was attempted (executed or budget-refused), in execution order.
    /// Goals that were purely blocked by upstream failures do not appear here.
    pub records: Vec<GoalRecord>,
    /// The highest `supervisor.in_flight()` observed at any point during this run.
    pub peak_concurrency: usize,
    /// True when the mission was halted because the mission-level budget was exhausted.
    pub mission_budget_exhausted: bool,
    /// Independent verification of the supervisor chain and every goal chain.
    pub chain_verify: MissionVerify,
    /// The workspace this run used — callers can open the run ledger from here.
    pub workspace: std::path::PathBuf,
}

impl MissionReport {
    /// Goals that reached `backend.execute` (not stopped by a budget check beforehand).
    pub fn executed_goals(&self) -> impl Iterator<Item = &GoalRecord> {
        self.records.iter().filter(|r| !r.budget_refused)
    }

    /// True when every executed goal held both a lease and a worktree at execution time.
    pub fn all_executed_held_lease_and_worktree(&self) -> bool {
        self.executed_goals().all(|r| r.had_lease_at_execution && r.had_worktree_at_execution)
    }
}

/// Run one mission end-to-end, injecting the execution backend.
///
/// `goals` is a slice of `(goal_id, prerequisites)` pairs in topological order — every goal's
/// prerequisites must appear before it in the slice. All goal ids must be unique.
///
/// The `workspace` directory is used for trace chains, the run ledger, and per-goal worktrees; it
/// need not exist before the call.
pub fn run_mission(
    goals: &[(&str, &[&str])],
    config: MissionConfig,
    workspace: &Path,
    backend: &dyn ExecutionBackend,
) -> MissionReport {
    // ── Build the goal graph ──────────────────────────────────────────────────────────────────────
    let mut dag = GoalDag::new();
    for (goal, prereqs) in goals {
        dag.add_goal(goal, prereqs)
            .unwrap_or_else(|e| panic!("DAG construction error for {goal}: {e:?}"));
    }
    let all_goals: Vec<String> = dag.goals();

    // ── Spine components ─────────────────────────────────────────────────────────────────────────
    let mut supervisor = Supervisor::with_capacity(config.capacity);
    let mut leases = LeaseRegistry::new();
    let mut worktrees = WorktreeRegistry::new(workspace.join("worktrees"));
    let mut budget = BudgetLedger::new(config.mission_limits, config.goal_limits);
    let mut lifecycle = Lifecycle::new();
    let run_ledger = RunLedger::at(workspace.join("run-ledger.jsonl"));
    let chains = MissionChains::in_workspace(workspace);
    let sup_chain = chains.supervisor();

    // ── Run state ────────────────────────────────────────────────────────────────────────────────
    let mut records: Vec<GoalRecord> = Vec::new();
    let mut peak_concurrency: usize = 0;
    let mut mission_budget_exhausted = false;
    let mut clock: u64 = 1;

    // ── Main scheduling loop ──────────────────────────────────────────────────────────────────────
    //
    // Each outer iteration:
    //   Phase 1 — admit every currently-ready goal into the supervisor's queue.
    //   Phase 2 — execute all admitted goals, promoting deferred goals as slots free.
    //
    // The inner `to_run` list grows as `supervisor.next_ready()` promotes deferred goals, so all
    // work admitted during one outer iteration is fully drained before the next iteration begins.
    // This keeps `supervisor.in_flight() == 0` at the top of every outer iteration, which lets
    // Phase 1 admit fresh goals cleanly.
    'main: loop {
        if dag.is_settled() {
            break;
        }

        // Phase 1 — Admit every currently-ready goal.
        //
        // A goal already in the deferred queue returns `Deferred` again; `next_ready` in Phase 2
        // will promote it when a slot opens.  All three `Admission` variants are matched
        // explicitly — no wildcard.
        let mut newly_admitted: Vec<String> = Vec::new();
        for goal in dag.ready() {
            match supervisor.admit(&goal) {
                Admission::Admitted => {
                    peak_concurrency = peak_concurrency.max(supervisor.in_flight());
                    newly_admitted.push(goal);
                }
                Admission::Deferred => { /* waiting for a slot; next_ready will pick it up */ }
                Admission::RefusedZeroCapacity => {
                    // Capacity is zero — no slot can ever open; stop immediately.
                    break 'main;
                }
            }
        }

        // Safety valve: if nothing was admitted and nothing is waiting, the DAG is stuck.
        // (Correct DAGs without cycles should never hit this.)
        if newly_admitted.is_empty() && supervisor.deferred() == 0 {
            break;
        }

        // Phase 2 — Execute admitted goals, growing the list as deferred goals are promoted.
        let mut to_run: Vec<String> = newly_admitted;
        let mut idx: usize = 0;
        while idx < to_run.len() {
            let goal = to_run[idx].clone();
            idx += 1;

            // ── Budget check — goal is charged before execution ───────────────────────────────
            //
            // Goal-level scope: only this goal stops; the mission continues.
            // Mission-level scope: the whole mission stops.
            if let Err(e) = budget.charge_tokens(&goal, 1) {
                supervisor.complete(&goal);

                // Mark terminal so downstream goals are blocked and reconcile can sweep later.
                lifecycle.admit(&goal);
                lifecycle.fail(&goal, format!("{e}")).ok();
                dag.mark_failed(&goal).ok();

                records.push(GoalRecord {
                    goal: goal.clone(),
                    outcome: GoalOutcome::Failed,
                    had_lease_at_execution: false,
                    had_worktree_at_execution: false,
                    budget_refused: true,
                });

                if e.scope == Scope::Mission {
                    mission_budget_exhausted = true;
                    reconcile(&mut leases, &lifecycle);
                    break 'main;
                }

                // The slot is now free — promote any deferred goal.
                while let Some(next) = supervisor.next_ready() {
                    peak_concurrency = peak_concurrency.max(supervisor.in_flight());
                    to_run.push(next);
                }
                continue;
            }

            // ── Acquire lease (must succeed: the slot was just admitted for a fresh goal) ─────
            let _lease = leases
                .acquire(&goal, "mission-runner", clock, u64::MAX / 2)
                .unwrap_or_else(|e| panic!("lease acquisition failed for {goal}: {e:?}"));
            clock += 1;

            // ── Worktree — exclusive workspace beneath `workspace/worktrees/` ─────────────────
            worktrees.assign_or_existing(&goal).ok();

            // Isolation evidence: snapshot resource state at the instant before execution.
            // These booleans capture what was true then; post-execution cleanup does not change them.
            let had_lease = leases.current(&goal).is_some();
            let had_worktree = worktrees.may_execute(&goal);

            // ── Lifecycle — start tracking the goal ───────────────────────────────────────────
            lifecycle.admit(&goal);

            // ── Supervisor trace chain ────────────────────────────────────────────────────────
            sup_chain
                .append("schedule", &goal, true, "admitted", &format!("{goal} admitted"))
                .ok();

            // ── Execute ───────────────────────────────────────────────────────────────────────
            let job = Job::new(&goal, &goal);
            let outcome = backend.execute(&job);
            let succeeded = outcome.status == BackendStatus::Completed;

            // ── Goal trace chain ─────────────────────────────────────────────────────────────
            let goal_chain = chains.goal(&goal);
            let signal = if succeeded { "completed" } else { "failed" };
            goal_chain.append("execute", &goal, succeeded, signal, &outcome.detail).ok();

            // ── Run ledger — one durable entry per execution ──────────────────────────────────
            let artifacts = if succeeded {
                RunArtifacts::none_for(&outcome.backend)
            } else {
                RunArtifacts::none_for(&outcome.backend).with_error(outcome.detail.clone())
            };
            run_ledger.record(&goal, &artifacts).ok();

            // ── Update DAG and lifecycle ──────────────────────────────────────────────────────
            let dag_outcome = if succeeded {
                dag.mark_succeeded(&goal).ok();
                lifecycle.complete(&goal).ok();
                GoalOutcome::Succeeded
            } else {
                dag.mark_failed(&goal).ok();
                lifecycle.fail(&goal, "execution failed").ok();
                GoalOutcome::Failed
            };

            // ── Release supervisor slot and worktree ──────────────────────────────────────────
            supervisor.complete(&goal);
            worktrees.release(&goal);

            // ── Reconcile: reclaim the lease now that the goal is terminal ────────────────────
            reconcile(&mut leases, &lifecycle);

            // ── Promote deferred goals into the freed slot ────────────────────────────────────
            while let Some(next) = supervisor.next_ready() {
                peak_concurrency = peak_concurrency.max(supervisor.in_flight());
                to_run.push(next);
            }

            records.push(GoalRecord {
                goal: goal.clone(),
                outcome: dag_outcome,
                had_lease_at_execution: had_lease,
                had_worktree_at_execution: had_worktree,
                budget_refused: false,
            });
        }
    }

    // ── Final reconciliation sweep ────────────────────────────────────────────────────────────────
    reconcile(&mut leases, &lifecycle);

    // ── Verify all trace chains ───────────────────────────────────────────────────────────────────
    let goal_refs: Vec<&str> = all_goals.iter().map(String::as_str).collect();
    let chain_verify = verify_mission(&chains, &goal_refs);

    MissionReport {
        settled: dag.is_settled(),
        records,
        peak_concurrency,
        mission_budget_exhausted,
        chain_verify,
        workspace: workspace.to_path_buf(),
    }
}
