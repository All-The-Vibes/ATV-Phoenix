//! `mission` — composition root: assembles the supervisor spine end-to-end.
//!
//! Every spine module is individually proven in its own tests; this module wires them into a
//! runner that can execute a complete mission. The execution backend is injected so the runner is
//! testable without real processes or network.
//!
//! ## Concurrency model
//!
//! Goals admitted together execute **concurrently**, one OS thread per goal, joined before the
//! batch settles. The `Supervisor` bounds how many goals are admitted at once, so `capacity` is a
//! real parallelism limit: `supervisor.in_flight()` never exceeds it, and up to that many
//! `backend.execute` calls are in flight simultaneously.
//!
//! Only `backend.execute` runs off the main thread. Every piece of coordination state — the DAG,
//! supervisor, lease registry, worktree registry, budget ledger, lifecycle, run ledger, and the
//! hash-chained traces — is touched exclusively by the scheduler thread, between batches. That is
//! deliberate: the trace chains are hash-linked, so concurrent appends would corrupt the very
//! record used to prove what happened. Isolation is enforced *before* dispatch and settled
//! *after*, never during.
//!
//! Because the scheduler joins each batch in spawn order, `records` stays deterministic even
//! though execution overlapped.
//!
//! ## Backend must be `Sync`
//!
//! `backend` is `&(dyn ExecutionBackend + Sync)` rather than a plain `&dyn ExecutionBackend`: it is
//! shared across threads. The bound sits on the parameter, not on the `ExecutionBackend` trait, so
//! single-threaded backends (including the `RefCell`-based cloud-client doubles) remain valid
//! implementations — they simply cannot be handed to the mission runner.
//!
//! ## Admission variants — exhaustive, no wildcard
//!
//! Every arm of `Admission` is matched explicitly: `Admitted`, `Deferred`, and
//! `RefusedZeroCapacity`. A wildcard arm would silently swallow the next variant the type gains,
//! which is exactly the defect that caused PR #122 to break.
//!
//! INVARIANT: every executed goal held both a lease and a worktree at the instant it executed.
//! Without a lease two workers can own one goal; without a worktree they share a checkout.
//! `MissionReport::all_executed_held_lease_and_worktree` reports it so a test can assert the
//! property rather than trust the wiring.
//! INVARIANT: coordination state is touched only by the scheduler thread, between batches. The
//! trace chains are hash-linked, so a concurrent append would corrupt the very record used to prove
//! what happened.
//! INVARIANT: reconciliation runs at every batch boundary and again at mission end, so a lease held
//! by a goal that stopped is always reclaimed — including when it stopped by dying, which is the
//! case an unwind-on-failure cleanup cannot reach.

use std::path::Path;

use crate::budget::{BudgetLedger, Limits, Scope};
use crate::execution_backend::{BackendOutcome, BackendStatus, ExecutionBackend, Job};
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

/// Resources reserved for one goal, captured before dispatch.
///
/// The two booleans record what was true at the instant `execute` was called; later cleanup does
/// not rewrite them, so a test can assert isolation actually held rather than that it holds now.
struct Prepared {
    goal: String,
    had_lease: bool,
    had_worktree: bool,
}

/// Run one mission end-to-end, injecting the execution backend.
///
/// `goals` is a slice of `(goal_id, prerequisites)` pairs in topological order — every goal's
/// prerequisites must appear before it in the slice. All goal ids must be unique.
///
/// Goals admitted together run concurrently (see the module docs); `config.capacity` bounds how
/// many execute at once.
///
/// The `workspace` directory is used for trace chains, the run ledger, and per-goal worktrees; it
/// need not exist before the call.
pub fn run_mission(
    goals: &[(&str, &[&str])],
    config: MissionConfig,
    workspace: &Path,
    backend: &(dyn ExecutionBackend + Sync),
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

        // Phase 2 — Drain admitted work in concurrent batches.
        //
        // Each batch: reserve resources single-threaded, execute the whole batch concurrently,
        // then settle it single-threaded. Completing a batch frees slots, so `next_ready`
        // promotes deferred goals into the following batch until nothing is left.
        let mut pending: Vec<String> = newly_admitted;
        while !pending.is_empty() {
            let batch: Vec<String> = std::mem::take(&mut pending);

            // ── 2a. Reserve resources for each goal (scheduler thread only) ───────────────────
            let mut prepared: Vec<Prepared> = Vec::new();
            for goal in batch {
                // ── Budget check — goal is charged before execution ───────────────────────────
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

                    continue;
                }

                // ── Acquire lease (must succeed: the slot was just admitted for a fresh goal) ─
                let _lease = leases
                    .acquire(&goal, "mission-runner", clock, u64::MAX / 2)
                    .unwrap_or_else(|e| panic!("lease acquisition failed for {goal}: {e:?}"));
                clock += 1;

                // ── Worktree — exclusive workspace beneath `workspace/worktrees/` ─────────────
                worktrees.assign_or_existing(&goal).ok();

                // Isolation evidence: snapshot resource state at the instant before execution.
                let had_lease = leases.current(&goal).is_some();
                let had_worktree = worktrees.may_execute(&goal);

                // ── Lifecycle — start tracking the goal ───────────────────────────────────────
                lifecycle.admit(&goal);

                // ── Supervisor trace chain ───────────────────────────────────────────────────
                sup_chain
                    .append("schedule", &goal, true, "admitted", &format!("{goal} admitted"))
                    .ok();

                prepared.push(Prepared { goal, had_lease, had_worktree });
            }

            // ── 2b. Execute the batch CONCURRENTLY ────────────────────────────────────────────
            //
            // One thread per goal. Nothing but `backend.execute` runs here, so no coordination
            // state is shared across threads. Results are joined in spawn order, keeping
            // `records` deterministic despite the overlap.
            //
            // A panicking backend becomes a failed outcome rather than unwinding the scheduler:
            // this runs inside a long-lived server, where one bad job must not kill the mission.
            let outcomes: Vec<BackendOutcome> = std::thread::scope(|scope| {
                let handles: Vec<_> = prepared
                    .iter()
                    .map(|p| {
                        let job = Job::new(&p.goal, &p.goal);
                        scope.spawn(move || backend.execute(&job))
                    })
                    .collect();

                handles
                    .into_iter()
                    .zip(prepared.iter())
                    .map(|(handle, p)| {
                        handle.join().unwrap_or_else(|_| {
                            BackendOutcome::failed(
                                &p.goal,
                                backend.name(),
                                "backend panicked during execution",
                            )
                        })
                    })
                    .collect()
            });

            // ── 2c. Settle the batch (scheduler thread only) ──────────────────────────────────
            for (p, outcome) in prepared.into_iter().zip(outcomes) {
                let goal = p.goal;
                let succeeded = outcome.status == BackendStatus::Completed;

                // ── Goal trace chain ─────────────────────────────────────────────────────────
                let goal_chain = chains.goal(&goal);
                let signal = if succeeded { "completed" } else { "failed" };
                goal_chain.append("execute", &goal, succeeded, signal, &outcome.detail).ok();

                // ── Run ledger — one durable entry per execution ──────────────────────────────
                let artifacts = if succeeded {
                    RunArtifacts::none_for(&outcome.backend)
                } else {
                    RunArtifacts::none_for(&outcome.backend).with_error(outcome.detail.clone())
                };
                run_ledger.record(&goal, &artifacts).ok();

                // ── Update DAG and lifecycle ──────────────────────────────────────────────────
                let dag_outcome = if succeeded {
                    dag.mark_succeeded(&goal).ok();
                    lifecycle.complete(&goal).ok();
                    GoalOutcome::Succeeded
                } else {
                    dag.mark_failed(&goal).ok();
                    lifecycle.fail(&goal, "execution failed").ok();
                    GoalOutcome::Failed
                };

                // ── Release supervisor slot and worktree ──────────────────────────────────────
                supervisor.complete(&goal);
                worktrees.release(&goal);

                records.push(GoalRecord {
                    goal,
                    outcome: dag_outcome,
                    had_lease_at_execution: p.had_lease,
                    had_worktree_at_execution: p.had_worktree,
                    budget_refused: false,
                });
            }

            // ── Reconcile: reclaim leases now that the batch is terminal ──────────────────────
            reconcile(&mut leases, &lifecycle);

            // ── Promote deferred goals into the freed slots ───────────────────────────────────
            while let Some(next) = supervisor.next_ready() {
                peak_concurrency = peak_concurrency.max(supervisor.in_flight());
                pending.push(next);
            }
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
