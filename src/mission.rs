//! `mission` — composition root that wires the supervisor spine end-to-end.
//!
//! This module intentionally contains orchestration only. It assembles the existing pure supervisor
//! primitives (`hybrid_dag`, `supervisor`, `lease`, `worktrees`, `budget`, `lifecycle`, `run_ledger`,
//! `trace_chains`, `reconcile`) and drives them through an injected [`crate::ExecutionBackend`].

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::path::{Path, PathBuf};

use crate::budget::{BudgetLedger, Limits, Scope};
use crate::execution_backend::{BackendStatus, ExecutionBackend, Job};
use crate::hybrid_dag::{DagDenied, GoalDag};
use crate::lease::LeaseRegistry;
use crate::lifecycle::Lifecycle;
use crate::reconcile::reconcile;
use crate::run_artifacts::RunArtifacts;
use crate::run_ledger::{LedgerRead, RunLedger};
use crate::supervisor::{Admission, Supervisor};
use crate::trace_chains::{verify_mission, MissionVerify, MissionChains};
use crate::worktrees::WorktreeRegistry;

/// One declared mission goal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MissionGoal {
    pub id: String,
    pub task: String,
    pub prerequisites: Vec<String>,
    pub budget_tokens: u64,
}

impl MissionGoal {
    pub fn new(id: impl Into<String>, task: impl Into<String>, prerequisites: Vec<String>) -> Self {
        Self { id: id.into(), task: task.into(), prerequisites, budget_tokens: 1 }
    }

    pub fn with_budget_tokens(mut self, budget_tokens: u64) -> Self {
        self.budget_tokens = budget_tokens;
        self
    }
}

/// Runtime settings for one mission run.
#[derive(Debug, Clone)]
pub struct MissionConfig {
    pub concurrency: usize,
    pub mission_limits: Limits,
    pub goal_limits: Limits,
    pub mission_dir: PathBuf,
    pub worktree_root: PathBuf,
    pub lease_holder: String,
    pub lease_ttl: u64,
    pub token_charge_per_goal: u64,
}

impl MissionConfig {
    pub fn in_dir(mission_dir: &Path) -> Self {
        Self {
            concurrency: 1,
            mission_limits: Limits::unlimited(),
            goal_limits: Limits::unlimited(),
            mission_dir: mission_dir.to_path_buf(),
            worktree_root: mission_dir.join("worktrees"),
            lease_holder: "mission-runner".to_string(),
            lease_ttl: 60,
            token_charge_per_goal: 1,
        }
    }
}

/// Execution-time invariants captured for each goal that actually ran.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GoalExecutionRecord {
    pub goal: String,
    pub had_valid_lease: bool,
    pub had_worktree_assignment: bool,
}

/// Outcome of a full mission run.
#[derive(Debug, Clone)]
pub struct MissionReport {
    pub execution_order: Vec<String>,
    pub blocked: Vec<String>,
    pub failed: Vec<String>,
    pub goal_budget_exhausted: Vec<String>,
    pub mission_budget_exhausted: bool,
    pub peak_in_flight: usize,
    pub execution_records: Vec<GoalExecutionRecord>,
    pub ledger: LedgerRead,
    pub traces: MissionVerify,
    pub settled: bool,
}

/// Mission composition root: one fully wired mission state machine.
#[derive(Debug, Clone)]
pub struct MissionRunner {
    dag: GoalDag,
    goals: BTreeMap<String, MissionGoal>,
    declared_order: Vec<String>,
    supervisor: Supervisor,
    leases: LeaseRegistry,
    budgets: BudgetLedger,
    lifecycle: Lifecycle,
    worktrees: WorktreeRegistry,
    ledger: RunLedger,
    chains: MissionChains,
    lease_holder: String,
    lease_ttl: u64,
    token_charge_per_goal: u64,
    now: u64,
    peak_in_flight: usize,
    scheduled: BTreeSet<String>,
    ready_queue: VecDeque<String>,
}

impl MissionRunner {
    pub fn new(goals: Vec<MissionGoal>, config: MissionConfig) -> Result<Self, DagDenied> {
        let mut dag = GoalDag::new();
        let mut goal_tasks = BTreeMap::new();
        let mut declared_order = Vec::new();
        for goal in goals {
            let prereqs: Vec<&str> = goal.prerequisites.iter().map(String::as_str).collect();
            dag.add_goal(&goal.id, &prereqs)?;
            declared_order.push(goal.id.clone());
            goal_tasks.insert(goal.id.clone(), goal);
        }

        Ok(Self {
            dag,
            goals: goal_tasks,
            declared_order,
            supervisor: Supervisor::with_capacity(config.concurrency),
            leases: LeaseRegistry::new(),
            budgets: BudgetLedger::new(config.mission_limits, config.goal_limits),
            lifecycle: Lifecycle::new(),
            worktrees: WorktreeRegistry::new(config.worktree_root),
            ledger: RunLedger::in_mission(&config.mission_dir),
            chains: MissionChains::in_workspace(&config.mission_dir),
            lease_holder: config.lease_holder,
            lease_ttl: config.lease_ttl,
            token_charge_per_goal: config.token_charge_per_goal,
            now: 0,
            peak_in_flight: 0,
            scheduled: BTreeSet::new(),
            ready_queue: VecDeque::new(),
        })
    }

    pub fn run(&mut self, backend: &dyn ExecutionBackend) -> MissionReport {
        let mut execution_order = Vec::new();
        let mut goal_budget_exhausted = Vec::new();
        let mut mission_budget_exhausted = false;
        let mut execution_records = Vec::new();

        loop {
            let mut progressed = false;

            for goal in self.dag.ready() {
                if !self.scheduled.insert(goal.clone()) {
                    continue;
                }
                progressed = true;
                match self.supervisor.admit(&goal) {
                    Admission::Admitted => {
                        self.peak_in_flight = self.peak_in_flight.max(self.supervisor.in_flight());
                        self.ready_queue.push_back(goal.clone());
                        let _ = self.chains.supervisor().append(
                            "schedule",
                            "admit",
                            true,
                            "ready",
                            &format!("{goal} admitted"),
                        );
                    }
                    Admission::Deferred => {
                        let _ = self.chains.supervisor().append(
                            "schedule",
                            "defer",
                            true,
                            "ready",
                            &format!("{goal} deferred"),
                        );
                    }
                }
            }

            while let Some(goal) = self.supervisor.next_ready() {
                progressed = true;
                self.peak_in_flight = self.peak_in_flight.max(self.supervisor.in_flight());
                self.ready_queue.push_back(goal.clone());
                let _ = self.chains.supervisor().append(
                    "schedule",
                    "promote",
                    true,
                    "ready",
                    &format!("{goal} promoted"),
                );
            }

            let Some(goal) = self.ready_queue.pop_front() else {
                if mission_budget_exhausted {
                    break;
                }
                if self.dag.is_settled() && self.supervisor.in_flight() == 0 && self.supervisor.deferred() == 0 {
                    break;
                }
                if !progressed {
                    break;
                }
                continue;
            };
            self.lifecycle.admit(&goal);
            self.now = self.now.saturating_add(1);

            let token_charge = self
                .goals
                .get(&goal)
                .map(|g| g.budget_tokens)
                .unwrap_or(self.token_charge_per_goal);
            match self.budgets.charge_tokens(&goal, token_charge) {
                Ok(()) => {}
                Err(err) => {
                    let _ = self.lifecycle.fail(&goal, err.to_string());
                    let _ = self.dag.mark_failed(&goal);
                    let _ = self
                        .chains
                        .goal(&goal)
                        .append("budget", "tokens", false, "charge", &err.to_string());
                    let _ = self.chains.supervisor().append(
                        "budget",
                        "tokens",
                        false,
                        "charge",
                        &format!("{goal}: {err}"),
                    );
                    let _ = self.supervisor.complete(&goal);
                    let sweep = reconcile(&mut self.leases, &self.lifecycle);
                    for reclaimed in sweep.reclaimed {
                        let _ = self.worktrees.release(&reclaimed.goal);
                    }
                    if err.scope == Scope::Mission {
                        mission_budget_exhausted = true;
                        break;
                    }
                    goal_budget_exhausted.push(goal.clone());
                    continue;
                }
            }

            let lease = match self
                .leases
                .acquire(&goal, &self.lease_holder, self.now, self.lease_ttl)
            {
                Ok(lease) => lease,
                Err(err) => {
                    let _ = self.lifecycle.fail(&goal, format!("lease refused: {err:?}"));
                    let _ = self.dag.mark_failed(&goal);
                    let _ = self
                        .chains
                        .goal(&goal)
                        .append("lease", "acquire", false, "refused", &format!("{err:?}"));
                    let _ = self.supervisor.complete(&goal);
                    continue;
                }
            };

            if self.worktrees.assign_or_existing(&goal).is_err() {
                let _ = self.lifecycle.fail(&goal, "worktree assignment refused");
                let _ = self.dag.mark_failed(&goal);
                let _ = self
                    .chains
                    .goal(&goal)
                    .append("worktree", "assign", false, "refused", "worktree assignment refused");
                let _ = self.supervisor.complete(&goal);
                let _ = self.leases.release(&goal, lease.token);
                continue;
            }

            let had_valid_lease = self.leases.is_valid(&goal, lease.token, self.now);
            let had_worktree_assignment = self.worktrees.may_execute(&goal);
            execution_records.push(GoalExecutionRecord {
                goal: goal.clone(),
                had_valid_lease,
                had_worktree_assignment,
            });

            let task = self.goals.get(&goal).map(|g| g.task.clone()).unwrap_or_default();
            let outcome = backend.execute(&Job::new(goal.clone(), task));
            let mut artifacts = RunArtifacts::none_for(outcome.backend.clone());
            if outcome.status == BackendStatus::Failed {
                artifacts = artifacts.with_error(outcome.detail.clone());
            }
            let _ = self.ledger.record(&goal, &artifacts);

            let goal_ok = outcome.status == BackendStatus::Completed && had_valid_lease && had_worktree_assignment;
            if goal_ok {
                let _ = self.dag.mark_succeeded(&goal);
                let _ = self.lifecycle.complete(&goal);
            } else {
                let _ = self.dag.mark_failed(&goal);
                let reason = if outcome.status == BackendStatus::Failed {
                    outcome.detail.clone()
                } else {
                    "execution preconditions not met".to_string()
                };
                let _ = self.lifecycle.fail(&goal, reason);
            }

            let _ = self.chains.goal(&goal).append(
                "execute",
                &outcome.job_id,
                goal_ok,
                "backend",
                &outcome.detail,
            );
            let _ = self.chains.supervisor().append(
                "execute",
                &outcome.job_id,
                goal_ok,
                "backend",
                &format!("{goal} via {}", outcome.backend),
            );
            execution_order.push(goal.clone());

            let _ = self.supervisor.complete(&goal);
            let sweep = reconcile(&mut self.leases, &self.lifecycle);
            for reclaimed in sweep.reclaimed {
                let _ = self.worktrees.release(&reclaimed.goal);
            }
            self.now = self.now.saturating_add(1);
        }

        let goal_refs: Vec<&str> = self.declared_order.iter().map(String::as_str).collect();
        MissionReport {
            execution_order,
            blocked: self.dag.blocked(),
            failed: self.dag.failed(),
            goal_budget_exhausted,
            mission_budget_exhausted,
            peak_in_flight: self.peak_in_flight,
            execution_records,
            ledger: self.ledger.read(),
            traces: verify_mission(&self.chains, &goal_refs),
            settled: self.dag.is_settled() || mission_budget_exhausted,
        }
    }
}
