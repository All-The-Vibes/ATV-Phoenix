use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::budget::{BudgetExceeded, BudgetLedger, Limits, Scope};
use crate::execution_backend::{BackendStatus, ExecutionBackend, Job};
use crate::hybrid_dag::{DagDenied, GoalDag, GoalOutcome};
use crate::lease::{LeaseDenied, LeaseRegistry};
use crate::lifecycle::{Lifecycle, TransitionDenied};
use crate::reconcile::reconcile;
use crate::run_artifacts::RunArtifacts;
use crate::run_ledger::{LedgerRead, RunLedger};
use crate::supervisor::{Admission, Supervisor};
use crate::trace_chains::{verify_mission, MissionChains, MissionVerify};
use crate::worktrees::{AssignmentDenied, WorktreeRegistry};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MissionGoal {
    pub id: String,
    pub task: String,
    pub prerequisites: Vec<String>,
    pub token_cost: u64,
}

impl MissionGoal {
    pub fn new(
        id: impl Into<String>,
        task: impl Into<String>,
        prerequisites: Vec<String>,
        token_cost: u64,
    ) -> Self {
        Self {
            id: id.into(),
            task: task.into(),
            prerequisites,
            token_cost,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionRecord {
    pub goal: String,
    pub held_lease: bool,
    pub held_worktree: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MissionReport {
    pub completion_order: Vec<String>,
    pub executed: Vec<ExecutionRecord>,
    pub blocked: Vec<String>,
    pub failed: Vec<String>,
    pub settled: bool,
    pub max_in_flight: usize,
    pub mission_budget_exhausted: bool,
}

#[derive(Debug)]
pub enum MissionError {
    Dag(DagDenied),
    Io(std::io::Error),
    Transition(TransitionDenied),
}

impl std::fmt::Display for MissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Dag(err) => write!(f, "dag error: {err:?}"),
            Self::Io(err) => write!(f, "io error: {err}"),
            Self::Transition(err) => write!(f, "transition error: {err}"),
        }
    }
}

impl std::error::Error for MissionError {}

impl From<std::io::Error> for MissionError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<DagDenied> for MissionError {
    fn from(value: DagDenied) -> Self {
        Self::Dag(value)
    }
}

impl From<TransitionDenied> for MissionError {
    fn from(value: TransitionDenied) -> Self {
        Self::Transition(value)
    }
}

pub struct MissionRunner {
    goals: BTreeMap<String, MissionGoal>,
    goal_order: Vec<String>,
    dag: GoalDag,
    supervisor: Supervisor,
    leases: LeaseRegistry,
    worktrees: WorktreeRegistry,
    budgets: BudgetLedger,
    lifecycle: Lifecycle,
    ledger: RunLedger,
    chains: MissionChains,
    now: u64,
    completion_order: Vec<String>,
    executed: Vec<ExecutionRecord>,
    max_in_flight: usize,
    mission_budget_exhausted: bool,
}

impl MissionRunner {
    pub fn new(
        workspace: &Path,
        worktree_root: impl Into<PathBuf>,
        goals: Vec<MissionGoal>,
        capacity: usize,
        mission_limits: Limits,
        goal_limits: Limits,
    ) -> Result<Self, MissionError> {
        let mut dag = GoalDag::new();
        let mut by_id = BTreeMap::new();
        let mut order = Vec::new();
        for goal in goals {
            let prereqs: Vec<&str> = goal.prerequisites.iter().map(String::as_str).collect();
            dag.add_goal(&goal.id, &prereqs)?;
            order.push(goal.id.clone());
            by_id.insert(goal.id.clone(), goal);
        }

        Ok(Self {
            goals: by_id,
            goal_order: order,
            dag,
            supervisor: Supervisor::with_capacity(capacity),
            leases: LeaseRegistry::new(),
            worktrees: WorktreeRegistry::new(worktree_root),
            budgets: BudgetLedger::new(mission_limits, goal_limits),
            lifecycle: Lifecycle::new(),
            ledger: RunLedger::in_mission(workspace),
            chains: MissionChains::in_workspace(workspace),
            now: 1,
            completion_order: Vec::new(),
            executed: Vec::new(),
            max_in_flight: 0,
            mission_budget_exhausted: false,
        })
    }

    pub fn run(&mut self, backend: &dyn ExecutionBackend) -> Result<MissionReport, MissionError> {
        while !self.dag.is_settled() && !self.mission_budget_exhausted {
            let ready = self.dag.ready();
            if ready.is_empty() {
                break;
            }

            let mut admitted = Vec::new();
            for goal in ready {
                let admission = self.supervisor.admit(&goal);
                self.record_supervisor_event(&goal, &admission)?;
                match admission {
                    Admission::Admitted => {
                        self.max_in_flight = self.max_in_flight.max(self.supervisor.in_flight());
                        admitted.push(goal);
                    }
                    Admission::Deferred => {}
                    Admission::RefusedZeroCapacity => {
                        self.fail_goal(&goal, "supervisor refused: zero capacity")?;
                    }
                }
            }

            let mut idx = 0;
            while idx < admitted.len() {
                let goal = admitted[idx].clone();
                idx += 1;
                self.execute_one(&goal, backend)?;
                while let Some(next) = self.supervisor.next_ready() {
                    self.max_in_flight = self.max_in_flight.max(self.supervisor.in_flight());
                    admitted.push(next);
                }
                if self.mission_budget_exhausted {
                    self.stop_mission_for_budget()?;
                }
            }
        }

        Ok(MissionReport {
            completion_order: self.completion_order.clone(),
            executed: self.executed.clone(),
            blocked: self.dag.blocked(),
            failed: self.dag.failed(),
            settled: self.dag.is_settled(),
            max_in_flight: self.max_in_flight,
            mission_budget_exhausted: self.mission_budget_exhausted,
        })
    }

    pub fn ledger_read(&self) -> LedgerRead {
        self.ledger.read()
    }

    pub fn verify_traces(&self) -> MissionVerify {
        let goals: Vec<&str> = self.goal_order.iter().map(String::as_str).collect();
        verify_mission(&self.chains, &goals)
    }

    fn execute_one(
        &mut self,
        goal: &str,
        backend: &dyn ExecutionBackend,
    ) -> Result<(), MissionError> {
        self.lifecycle.admit(goal);
        let goal_cfg = self.goals.get(goal).expect("goal exists");

        if let Err(err) = self.budgets.charge_tokens(goal, goal_cfg.token_cost) {
            self.fail_for_budget(goal, err)?;
            self.supervisor.complete(goal);
            reconcile(&mut self.leases, &self.lifecycle);
            self.worktrees.release(goal);
            return Ok(());
        }

        let lease = match self.leases.acquire(goal, "mission-runner", self.now, 10) {
            Ok(lease) => lease,
            Err(LeaseDenied::Held) | Err(LeaseDenied::Stale) => {
                self.fail_goal(goal, "lease acquisition refused")?;
                self.supervisor.complete(goal);
                reconcile(&mut self.leases, &self.lifecycle);
                self.worktrees.release(goal);
                return Ok(());
            }
        };

        if let Err(err) = self.worktrees.assign_or_existing(goal) {
            let reason = match err {
                AssignmentDenied::AlreadyAssigned { .. } => "worktree already assigned".to_string(),
                AssignmentDenied::PathTaken { holder, path } => {
                    format!("worktree {} held by {holder}", path.display())
                }
            };
            self.fail_goal(goal, &reason)?;
            self.supervisor.complete(goal);
            reconcile(&mut self.leases, &self.lifecycle);
            self.worktrees.release(goal);
            return Ok(());
        }

        let held_lease = self
            .leases
            .current(goal)
            .is_some_and(|l| l.token == lease.token);
        let held_worktree = self.worktrees.may_execute(goal);
        self.executed.push(ExecutionRecord {
            goal: goal.to_string(),
            held_lease,
            held_worktree,
        });

        let job = Job::new(goal.to_string(), goal_cfg.task.clone());
        let outcome = backend.execute(&job);
        let mut artifacts = RunArtifacts::none_for(outcome.backend.clone());
        if outcome.status == BackendStatus::Failed {
            artifacts = artifacts.with_error(outcome.detail.clone());
        }
        self.ledger.record(goal, &artifacts)?;
        self.chains.goal(goal).append(
            "execute",
            goal,
            outcome.status == BackendStatus::Completed,
            backend.name(),
            &outcome.detail,
        )?;

        match outcome.status {
            BackendStatus::Completed => {
                self.lifecycle.complete(goal)?;
                self.dag.mark_succeeded(goal)?;
                self.completion_order.push(goal.to_string());
            }
            BackendStatus::Failed => {
                self.fail_goal(goal, &outcome.detail)?;
            }
        }

        self.supervisor.complete(goal);
        reconcile(&mut self.leases, &self.lifecycle);
        self.worktrees.release(goal);
        self.now = self.now.saturating_add(1);
        Ok(())
    }

    fn fail_for_budget(&mut self, goal: &str, err: BudgetExceeded) -> Result<(), MissionError> {
        let reason = err.to_string();
        self.fail_goal(goal, &reason)?;
        if err.scope == Scope::Mission {
            self.mission_budget_exhausted = true;
        }
        Ok(())
    }

    fn stop_mission_for_budget(&mut self) -> Result<(), MissionError> {
        for goal in self.goal_order.clone() {
            if self.dag.state(&goal) == Some(GoalOutcome::Pending) {
                self.fail_goal(&goal, "mission budget exhausted")?;
                self.supervisor.withdraw(&goal);
            }
        }
        Ok(())
    }

    fn fail_goal(&mut self, goal: &str, reason: &str) -> Result<(), MissionError> {
        self.lifecycle.admit(goal);
        if matches!(self.lifecycle.state(goal), Some(state) if state.is_terminal()) {
            return Ok(());
        }
        self.lifecycle.fail(goal, reason)?;
        self.dag.mark_failed(goal)?;
        Ok(())
    }

    fn record_supervisor_event(&self, goal: &str, admission: &Admission) -> std::io::Result<()> {
        let (ok, signal, evidence) = match admission {
            Admission::Admitted => (true, "admitted", format!("goal={goal}")),
            Admission::Deferred => (true, "deferred", format!("goal={goal}")),
            Admission::RefusedZeroCapacity => {
                (false, "refused_zero_capacity", format!("goal={goal}"))
            }
        };
        self.chains
            .supervisor()
            .append("schedule", goal, ok, signal, &evidence)
            .map(|_| ())
    }
}
