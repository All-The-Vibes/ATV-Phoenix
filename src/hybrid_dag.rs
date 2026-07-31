//! `hybrid_dag` — dependency-aware readiness with *contained* failure.
//!
//! The ready queue in [`crate::supervisor`] answers "is a slot free?". It does not answer "is this
//! goal allowed to run *yet*?" — it has no edges. This module supplies the missing half: a pure,
//! in-memory dependency graph that decides which goals are runnable, which are blocked because a
//! prerequisite failed, and — the property the mission actually depends on — which unrelated
//! branches must keep running anyway.
//!
//! Containment is the whole point. A mission that halts every goal because one unrelated branch
//! failed has traded a partial failure for a total one; a mission that runs a goal whose
//! prerequisite failed produces a result built on nothing and then merges it. Both are worse than
//! stopping exactly the affected subtree, which is what this does.
//!
//! Pure by construction: no async runtime, no git, no network. Those ride on top of this decision.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use crate::lease::{Fence, LeaseRegistry};
use crate::supervisor::Supervisor;

/// Where a goal stands in the mission.
///
/// `Blocked` is deliberately distinct from `Failed`: a blocked goal never ran. Collapsing the two
/// would make an audit unable to tell what broke from what never got a chance, and would point a
/// post-mortem at innocent goals.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GoalOutcome {
    /// Declared, not yet resolved.
    Pending,
    /// Ran and proved itself.
    Succeeded,
    /// Ran and did not.
    Failed,
    /// Never ran: an ancestor failed.
    Blocked,
}

impl GoalOutcome {
    /// Terminal states can never be moved again.
    pub fn is_terminal(self) -> bool {
        !matches!(self, GoalOutcome::Pending)
    }
}

/// Why the graph refused a request. Every refusal names a reason — a silently-dropped edge or
/// transition is indistinguishable from one that worked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DagDenied {
    /// A goal with this id is already declared.
    DuplicateGoal { goal: String },
    /// The goal listed itself as its own prerequisite.
    SelfDependency { goal: String },
    /// The prerequisite was never declared. Refused rather than assumed satisfied — a typo that
    /// reads as "no prerequisite" is how a goal runs before the thing it depends on.
    UnknownPrerequisite { goal: String, prerequisite: String },
    /// No such goal in this mission.
    UnknownGoal { goal: String },
    /// The goal already reached a terminal state.
    AlreadyResolved { goal: String, state: GoalOutcome },
    /// Success was claimed while a prerequisite had not succeeded — a stale or out-of-order result.
    NotReady { goal: String, prerequisite: String },
}

/// Where a goal is currently running.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GoalBackend {
    Local,
    CopilotCloud,
}

impl GoalBackend {
    fn holder(self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::CopilotCloud => "copilot_cloud",
        }
    }
}

/// One dispatch decision for a ready goal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GoalDispatch {
    pub goal: String,
    pub backend: GoalBackend,
    pub token: u64,
}

/// Explicit integration failures.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IntegrationFailure {
    Conflict { detail: String },
    Error { detail: String },
}

impl std::fmt::Display for IntegrationFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Conflict { detail } => write!(f, "merge conflict: {detail}"),
            Self::Error { detail } => f.write_str(detail),
        }
    }
}

impl std::error::Error for IntegrationFailure {}

/// Merge seam: production performs git merges; tests drive this deterministically.
pub trait IntegrationWorker {
    fn merge(
        &mut self,
        integration_worktree: &str,
        goal: &str,
        branch: &str,
    ) -> Result<(), IntegrationFailure>;
}

/// Why a hybrid mission step was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HybridDenied {
    UnknownGoal { goal: String },
    NotRunning { goal: String },
    WrongBackend {
        goal: String,
        expected: GoalBackend,
        got: GoalBackend,
    },
    SlaNotExpired { goal: String, now: u64, expires_at: u64 },
    StaleResult { goal: String, token: u64 },
    AlreadyResolved { goal: String, state: GoalOutcome },
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RunningGoal {
    backend: GoalBackend,
    token: u64,
    expires_at: u64,
}

/// Dedicated integration workspace for merging proven goal branches.
pub const INTEGRATION_WORKTREE: &str = "integration";

/// Runtime state for mixed local/cloud goal execution with fenced fallback.
#[derive(Debug, Clone)]
pub struct HybridMission {
    dag: GoalDag,
    local: Supervisor,
    leases: LeaseRegistry,
    cloud_queue_sla: u64,
    running: BTreeMap<String, RunningGoal>,
    proven_branches: BTreeMap<String, String>,
    integration_worktree: String,
    failures: BTreeMap<String, String>,
}

impl HybridMission {
    pub fn new(local_capacity: usize, cloud_queue_sla: u64) -> Self {
        Self {
            dag: GoalDag::new(),
            local: Supervisor::with_capacity(local_capacity),
            leases: LeaseRegistry::new(),
            cloud_queue_sla: cloud_queue_sla.max(1),
            running: BTreeMap::new(),
            proven_branches: BTreeMap::new(),
            integration_worktree: INTEGRATION_WORKTREE.to_string(),
            failures: BTreeMap::new(),
        }
    }

    pub fn add_goal(&mut self, goal: &str, prerequisites: &[&str]) -> Result<(), DagDenied> {
        self.dag.add_goal(goal, prerequisites)
    }

    pub fn ready(&self) -> Vec<String> {
        self.dag.ready()
    }

    pub fn state(&self, goal: &str) -> Option<GoalOutcome> {
        self.dag.state(goal)
    }

    pub fn blocked(&self) -> Vec<String> {
        self.dag.blocked()
    }

    pub fn failed(&self) -> Vec<String> {
        self.dag.failed()
    }

    pub fn failure_reason(&self, goal: &str) -> Option<&str> {
        self.failures.get(goal).map(String::as_str)
    }

    pub fn integration_worktree(&self) -> &str {
        &self.integration_worktree
    }

    pub fn watermark(&self, goal: &str) -> Option<u64> {
        self.leases.watermark(goal)
    }

    pub fn dispatch_ready(&mut self, now: u64) -> Vec<GoalDispatch> {
        let mut out = Vec::new();
        for goal in self.dag.ready() {
            if self.running.contains_key(&goal) || self.proven_branches.contains_key(&goal) {
                continue;
            }
            if let Some(dispatch) = self.dispatch_goal(&goal, now) {
                out.push(dispatch);
            }
        }
        out
    }

    /// Re-dispatch cloud goals whose queue wait exceeded SLA, advancing fencing on every retry.
    pub fn advance_expired_cloud_fences(&mut self, now: u64) -> Result<Vec<GoalDispatch>, HybridDenied> {
        let expired: Vec<String> = self
            .running
            .iter()
            .filter(|(_, run)| run.backend == GoalBackend::CopilotCloud && now >= run.expires_at)
            .map(|(g, _)| g.clone())
            .collect();

        let mut out = Vec::new();
        for goal in expired {
            self.running.remove(&goal);
            if let Some(dispatch) = self.dispatch_goal(&goal, now) {
                out.push(dispatch);
            }
        }
        Ok(out)
    }

    pub fn expire_cloud_goal(
        &mut self,
        goal: &str,
        now: u64,
    ) -> Result<Option<GoalDispatch>, HybridDenied> {
        let Some(run) = self.running.get(goal).cloned() else {
            return Err(HybridDenied::NotRunning { goal: goal.to_string() });
        };
        if run.backend != GoalBackend::CopilotCloud {
            return Err(HybridDenied::WrongBackend {
                goal: goal.to_string(),
                expected: GoalBackend::CopilotCloud,
                got: run.backend,
            });
        }
        if now < run.expires_at {
            return Err(HybridDenied::SlaNotExpired {
                goal: goal.to_string(),
                now,
                expires_at: run.expires_at,
            });
        }

        self.running.remove(goal);
        Ok(self.dispatch_goal(goal, now))
    }

    pub fn report_success(
        &mut self,
        goal: &str,
        backend: GoalBackend,
        token: u64,
        branch: &str,
        now: u64,
        integration: &mut dyn IntegrationWorker,
    ) -> Result<(), HybridDenied> {
        if let Some(run) = self.running.get(goal) {
            if run.backend != backend {
                return Err(HybridDenied::WrongBackend {
                    goal: goal.to_string(),
                    expected: run.backend,
                    got: backend,
                });
            }
        }

        if self.leases.commit(goal, token, now) == Fence::Fenced {
            return Err(HybridDenied::StaleResult { goal: goal.to_string(), token });
        }

        if let Some(run) = self.running.remove(goal) {
            if run.backend == GoalBackend::Local {
                self.local.complete(goal);
                while let Some(next) = self.local.next_ready() {
                    self.local.complete(&next);
                }
            }
        }
        self.leases.release(goal, token);
        self.proven_branches.insert(goal.to_string(), branch.to_string());
        self.integrate_proven(integration)
    }

    pub fn report_failure(
        &mut self,
        goal: &str,
        backend: GoalBackend,
        token: u64,
        reason: &str,
        now: u64,
    ) -> Result<Vec<String>, HybridDenied> {
        let Some(run) = self.running.get(goal).cloned() else {
            return Err(HybridDenied::NotRunning { goal: goal.to_string() });
        };
        if run.backend != backend {
            return Err(HybridDenied::WrongBackend {
                goal: goal.to_string(),
                expected: run.backend,
                got: backend,
            });
        }
        if self.leases.commit(goal, token, now) == Fence::Fenced {
            return Err(HybridDenied::StaleResult { goal: goal.to_string(), token });
        }

        self.running.remove(goal);
        if backend == GoalBackend::Local {
            self.local.complete(goal);
            while let Some(next) = self.local.next_ready() {
                self.local.complete(&next);
            }
        }
        self.leases.release(goal, token);
        self.failures.insert(goal.to_string(), reason.to_string());
        self.dag.mark_failed(goal).map_err(|e| map_dag_denied(goal, e))
    }

    fn dispatch_goal(&mut self, goal: &str, now: u64) -> Option<GoalDispatch> {
        if self.dag.state(goal) != Some(GoalOutcome::Pending) {
            return None;
        }

        let backend = if self.local.in_flight() < self.local.capacity() {
            self.local.admit(goal);
            GoalBackend::Local
        } else {
            GoalBackend::CopilotCloud
        };
        let ttl = if backend == GoalBackend::CopilotCloud {
            self.cloud_queue_sla
        } else {
            u64::MAX / 2
        };
        let lease = self.leases.acquire(goal, backend.holder(), now, ttl).ok()?;
        let run = RunningGoal {
            backend,
            token: lease.token,
            expires_at: lease.expires_at,
        };
        self.running.insert(goal.to_string(), run);
        Some(GoalDispatch { goal: goal.to_string(), backend, token: lease.token })
    }

    fn integrate_proven(&mut self, integration: &mut dyn IntegrationWorker) -> Result<(), HybridDenied> {
        loop {
            let mut progressed = false;
            for goal in self.dag.ready() {
                let Some(branch) = self.proven_branches.get(&goal).cloned() else {
                    continue;
                };
                match integration.merge(&self.integration_worktree, &goal, &branch) {
                    Ok(()) => {
                        self.proven_branches.remove(&goal);
                        self.dag.mark_succeeded(&goal).map_err(|e| map_dag_denied(&goal, e))?;
                    }
                    Err(err) => {
                        self.proven_branches.remove(&goal);
                        self.failures.insert(goal.clone(), err.to_string());
                        self.dag.mark_failed(&goal).map_err(|e| map_dag_denied(&goal, e))?;
                    }
                }
                progressed = true;
                break;
            }
            if !progressed {
                return Ok(());
            }
        }
    }
}

fn map_dag_denied(goal: &str, denied: DagDenied) -> HybridDenied {
    match denied {
        DagDenied::UnknownGoal { .. } => HybridDenied::UnknownGoal { goal: goal.to_string() },
        DagDenied::AlreadyResolved { goal, state } => HybridDenied::AlreadyResolved { goal, state },
        _ => HybridDenied::NotRunning { goal: goal.to_string() },
    }
}

/// A mission's goal graph: acyclic *by construction*, deterministic in every ordering it returns.
#[derive(Debug, Clone, Default)]
pub struct GoalDag {
    order: Vec<String>,
    prerequisites: BTreeMap<String, Vec<String>>,
    dependents: BTreeMap<String, Vec<String>>,
    state: BTreeMap<String, GoalOutcome>,
}

impl GoalDag {
    /// An empty mission.
    pub fn new() -> Self {
        Self::default()
    }

    /// Declare `goal`, depending on already-declared `prerequisites`.
    ///
    /// Requiring every prerequisite to predate its dependent makes a cycle **unrepresentable**
    /// rather than merely rejected: there is no call sequence that builds one, so there is no cycle
    /// detector to get wrong and no "ready" set left undefined by a deadlocked loop.
    pub fn add_goal(&mut self, goal: &str, prerequisites: &[&str]) -> Result<(), DagDenied> {
        if self.state.contains_key(goal) {
            return Err(DagDenied::DuplicateGoal { goal: goal.to_string() });
        }
        for p in prerequisites {
            if *p == goal {
                return Err(DagDenied::SelfDependency { goal: goal.to_string() });
            }
            if !self.state.contains_key(*p) {
                return Err(DagDenied::UnknownPrerequisite {
                    goal: goal.to_string(),
                    prerequisite: (*p).to_string(),
                });
            }
        }

        // Deduplicate while preserving declaration order: a repeated edge is harmless but would
        // otherwise be traversed twice.
        let mut seen = BTreeSet::new();
        let mut prereqs = Vec::new();
        for p in prerequisites {
            if seen.insert((*p).to_string()) {
                prereqs.push((*p).to_string());
            }
        }
        for p in &prereqs {
            self.dependents.entry(p.clone()).or_default().push(goal.to_string());
        }

        self.order.push(goal.to_string());
        self.prerequisites.insert(goal.to_string(), prereqs);
        self.state.insert(goal.to_string(), GoalOutcome::Pending);
        Ok(())
    }

    /// The current state of `goal`, if it is declared.
    pub fn state(&self, goal: &str) -> Option<GoalOutcome> {
        self.state.get(goal).copied()
    }

    /// Goals that may execute right now: pending, with **every** prerequisite succeeded.
    ///
    /// "Every prerequisite succeeded" — not "no prerequisite failed". A pending prerequisite is not
    /// permission to start.
    pub fn ready(&self) -> Vec<String> {
        self.order
            .iter()
            .filter(|g| self.state.get(*g) == Some(&GoalOutcome::Pending))
            .filter(|g| self.prereqs_satisfied(g))
            .cloned()
            .collect()
    }

    /// Goals that will never run because an ancestor failed, in declaration order.
    pub fn blocked(&self) -> Vec<String> {
        self.with_state(GoalOutcome::Blocked)
    }

    /// Goals that ran and failed, in declaration order.
    pub fn failed(&self) -> Vec<String> {
        self.with_state(GoalOutcome::Failed)
    }

    /// Every declared goal, in declaration order.
    pub fn goals(&self) -> Vec<String> {
        self.order.clone()
    }

    /// True once no goal is pending — the mission can be concluded.
    pub fn is_settled(&self) -> bool {
        !self.state.values().any(|s| *s == GoalOutcome::Pending)
    }

    /// Record that `goal` proved itself.
    ///
    /// Refused unless the goal was actually ready. A supervisor that accepts success out of
    /// dependency order accepts a result computed against a prerequisite that had not landed.
    pub fn mark_succeeded(&mut self, goal: &str) -> Result<(), DagDenied> {
        self.expect_pending(goal)?;
        let prereqs = self.prerequisites.get(goal).cloned().unwrap_or_default();
        for p in prereqs {
            if self.state.get(&p) != Some(&GoalOutcome::Succeeded) {
                return Err(DagDenied::NotReady { goal: goal.to_string(), prerequisite: p });
            }
        }
        self.state.insert(goal.to_string(), GoalOutcome::Succeeded);
        Ok(())
    }

    /// Record that `goal` failed, and block everything downstream of it.
    ///
    /// Returns the goals blocked *by this call*, in declaration order. Blocking walks dependents
    /// transitively — a grandchild of a failed goal is just as unrunnable as a child — but only
    /// along edges reachable from the failure, so branches that never depended on it are untouched.
    pub fn mark_failed(&mut self, goal: &str) -> Result<Vec<String>, DagDenied> {
        self.expect_pending(goal)?;
        self.state.insert(goal.to_string(), GoalOutcome::Failed);

        let mut newly: BTreeSet<String> = BTreeSet::new();
        let mut queue: VecDeque<String> = VecDeque::new();
        queue.push_back(goal.to_string());
        while let Some(current) = queue.pop_front() {
            let downstream = self.dependents.get(&current).cloned().unwrap_or_default();
            for d in downstream {
                // Already-terminal dependents are left alone: an already-blocked goal has already
                // propagated, and re-walking it would report the same goals twice.
                if self.state.get(&d) == Some(&GoalOutcome::Pending) {
                    self.state.insert(d.clone(), GoalOutcome::Blocked);
                    newly.insert(d.clone());
                    queue.push_back(d);
                }
            }
        }

        Ok(self.order.iter().filter(|g| newly.contains(*g)).cloned().collect())
    }

    fn with_state(&self, want: GoalOutcome) -> Vec<String> {
        self.order
            .iter()
            .filter(|g| self.state.get(*g) == Some(&want))
            .cloned()
            .collect()
    }

    fn prereqs_satisfied(&self, goal: &str) -> bool {
        self.prerequisites
            .get(goal)
            .map(|ps| ps.iter().all(|p| self.state.get(p) == Some(&GoalOutcome::Succeeded)))
            .unwrap_or(false)
    }

    fn expect_pending(&self, goal: &str) -> Result<(), DagDenied> {
        match self.state.get(goal) {
            None => Err(DagDenied::UnknownGoal { goal: goal.to_string() }),
            Some(GoalOutcome::Pending) => Ok(()),
            Some(other) => {
                Err(DagDenied::AlreadyResolved { goal: goal.to_string(), state: *other })
            }
        }
    }
}
