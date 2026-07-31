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
