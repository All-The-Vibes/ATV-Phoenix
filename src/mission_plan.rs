//! `mission_plan` — turn a caller-supplied goal list into something [`crate::mission::run_mission`]
//! can actually run.
//!
//! `run_mission` is proven, but it has two edges that any caller accepting *external* input has to
//! cover first:
//!
//! 1. **It panics on a malformed graph.** `run_mission` calls `dag.add_goal(..).unwrap_or_else(|e|
//!    panic!(..))`, so a duplicate id, a self-dependency, an unknown prerequisite, or a
//!    forward-declared one takes the whole process down. Inside a long-lived server that is not a
//!    failed tool call — it is a dead harness. [`plan`] refuses those inputs as values instead.
//!
//! 2. **It does not carry tasks.** Every job is built as `Job::new(goal_id, goal_id)`, so the goal
//!    id arrives at the backend *as the command*. A caller with real per-goal commands has to map
//!    them back on. [`TaskMapBackend`] does that, and it is applied automatically by
//!    [`MissionPlan::run`] so a call site cannot forget it.
//!
//! `run_mission` additionally requires goals in topological order ("every goal's prerequisites must
//! appear before it in the slice"). [`plan`] guarantees that ordering, and detects the cycles that
//! would otherwise surface as an `UnknownPrerequisite` panic with a misleading message.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use crate::execution_backend::{BackendOutcome, ExecutionBackend, Job, PreflightOutcome};
use crate::mission::{run_mission, MissionConfig, MissionReport};

/// One goal as supplied by a caller, before validation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GoalSpec {
    /// Unique identifier for this goal.
    pub id: String,
    /// Ids of goals that must succeed before this one runs. Empty means independent.
    pub depends_on: Vec<String>,
    /// The real work: an argv string (the local backend splits on whitespace, no shell).
    pub task: String,
}

impl GoalSpec {
    pub fn new(
        id: impl Into<String>,
        depends_on: impl IntoIterator<Item = impl Into<String>>,
        task: impl Into<String>,
    ) -> Self {
        Self {
            id: id.into(),
            depends_on: depends_on.into_iter().map(Into::into).collect(),
            task: task.into(),
        }
    }
}

/// Why a caller-supplied goal list cannot become a runnable DAG.
///
/// Every variant names the offending goal so the caller can fix the input rather than guess.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlanError {
    NoGoals,
    ZeroCapacity,
    DuplicateGoal { goal: String },
    SelfDependency { goal: String },
    UnknownPrerequisite { goal: String, prerequisite: String },
    EmptyTask { goal: String },
    /// The remaining goals form at least one cycle, so none of them can ever become ready.
    Cycle { goals: Vec<String> },
}

impl std::fmt::Display for PlanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NoGoals => write!(f, "no goals supplied"),
            Self::ZeroCapacity => {
                write!(f, "capacity must be at least 1; zero capacity can never admit a goal")
            }
            Self::DuplicateGoal { goal } => write!(f, "duplicate goal id {goal:?}"),
            Self::SelfDependency { goal } => write!(f, "goal {goal:?} depends on itself"),
            Self::UnknownPrerequisite { goal, prerequisite } => {
                write!(f, "goal {goal:?} depends on unknown goal {prerequisite:?}")
            }
            Self::EmptyTask { goal } => write!(f, "goal {goal:?} has an empty task"),
            Self::Cycle { goals } => {
                write!(f, "dependency cycle among goals {goals:?}")
            }
        }
    }
}

impl std::error::Error for PlanError {}

/// A validated, topologically ordered mission ready to hand to [`run_mission`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MissionPlan {
    ordered: Vec<GoalSpec>,
}

impl MissionPlan {
    /// The goals in execution-safe order: every goal appears after all of its prerequisites.
    pub fn ordered(&self) -> &[GoalSpec] {
        &self.ordered
    }

    pub fn len(&self) -> usize {
        self.ordered.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ordered.is_empty()
    }

    /// Run this plan, wrapping `inner` so each goal receives its declared task.
    ///
    /// This is the only supported way to execute a plan: wrapping is applied here so no call site
    /// can accidentally dispatch jobs whose task is still the goal id.
    pub fn run(
        &self,
        config: MissionConfig,
        workspace: &Path,
        inner: &dyn ExecutionBackend,
    ) -> MissionReport {
        // `run_mission` wants `&[(&str, &[&str])]`, so the borrowed prerequisite slices need
        // storage that outlives the call.
        let dep_refs: Vec<Vec<&str>> = self
            .ordered
            .iter()
            .map(|g| g.depends_on.iter().map(String::as_str).collect())
            .collect();
        let dag: Vec<(&str, &[&str])> = self
            .ordered
            .iter()
            .zip(dep_refs.iter())
            .map(|(g, deps)| (g.id.as_str(), deps.as_slice()))
            .collect();

        let backend = TaskMapBackend::new(inner, &self.ordered);
        run_mission(&dag, config, workspace, &backend)
    }
}

/// Validate a goal list and put it in topological order.
///
/// Ordering is deterministic: among goals that become ready simultaneously, the
/// lexicographically smallest id is emitted first, so the same input always plans the same way.
pub fn plan(goals: Vec<GoalSpec>) -> Result<MissionPlan, PlanError> {
    if goals.is_empty() {
        return Err(PlanError::NoGoals);
    }

    // ── Unique ids ────────────────────────────────────────────────────────────────────────────
    let mut seen: BTreeSet<&str> = BTreeSet::new();
    for g in &goals {
        if !seen.insert(g.id.as_str()) {
            return Err(PlanError::DuplicateGoal { goal: g.id.clone() });
        }
    }

    // ── Per-goal validity ─────────────────────────────────────────────────────────────────────
    for g in &goals {
        if g.task.trim().is_empty() {
            return Err(PlanError::EmptyTask { goal: g.id.clone() });
        }
        for dep in &g.depends_on {
            if dep == &g.id {
                return Err(PlanError::SelfDependency { goal: g.id.clone() });
            }
            if !seen.contains(dep.as_str()) {
                return Err(PlanError::UnknownPrerequisite {
                    goal: g.id.clone(),
                    prerequisite: dep.clone(),
                });
            }
        }
    }

    // ── Kahn's algorithm over a deterministic ready set ────────────────────────────────────────
    //
    // Duplicate edges are collapsed so a prerequisite listed twice does not inflate the in-degree
    // and strand a goal that is genuinely ready.
    let mut remaining: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    for g in &goals {
        remaining.insert(g.id.as_str(), g.depends_on.iter().map(String::as_str).collect());
    }

    let mut order: Vec<&str> = Vec::with_capacity(goals.len());
    while !remaining.is_empty() {
        let ready: Vec<&str> = remaining
            .iter()
            .filter(|(_, deps)| deps.is_empty())
            .map(|(id, _)| *id)
            .collect();

        if ready.is_empty() {
            // Nothing can advance and goals are left: every survivor is in or behind a cycle.
            return Err(PlanError::Cycle {
                goals: remaining.keys().map(|s| s.to_string()).collect(),
            });
        }

        for id in ready {
            remaining.remove(id);
            for deps in remaining.values_mut() {
                deps.remove(id);
            }
            order.push(id);
        }
    }

    let by_id: BTreeMap<&str, &GoalSpec> = goals.iter().map(|g| (g.id.as_str(), g)).collect();
    let ordered = order.iter().map(|id| (*by_id.get(id).expect("planned id exists")).clone()).collect();

    Ok(MissionPlan { ordered })
}

/// Wraps a backend so each job receives the task declared for its goal id.
///
/// [`run_mission`] builds jobs as `Job::new(goal_id, goal_id)`. Without this adapter the backend
/// would try to execute the goal id as a command.
///
/// A job id absent from the map is forwarded **unchanged** rather than given a default: the
/// mismatch then surfaces as a failed job in the run ledger instead of silently running something
/// nobody asked for.
pub struct TaskMapBackend<'a> {
    inner: &'a dyn ExecutionBackend,
    goals: &'a [GoalSpec],
}

impl<'a> TaskMapBackend<'a> {
    pub fn new(inner: &'a dyn ExecutionBackend, goals: &'a [GoalSpec]) -> Self {
        Self { inner, goals }
    }

    fn map_job(&self, job: &Job) -> Job {
        match self.goals.iter().find(|g| g.id == job.id) {
            Some(g) => Job::new(job.id.clone(), g.task.clone()),
            None => job.clone(),
        }
    }
}

impl ExecutionBackend for TaskMapBackend<'_> {
    fn name(&self) -> &str {
        self.inner.name()
    }

    fn preflight(&self, job: &Job) -> PreflightOutcome {
        self.inner.preflight(&self.map_job(job))
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        self.inner.execute(&self.map_job(job))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn g(id: &str, deps: &[&str]) -> GoalSpec {
        GoalSpec::new(id, deps.to_vec(), "rustc --version")
    }

    #[test]
    fn empty_input_is_refused() {
        assert_eq!(plan(vec![]).unwrap_err(), PlanError::NoGoals);
    }

    #[test]
    fn duplicate_ids_are_refused() {
        let err = plan(vec![g("a", &[]), g("a", &[])]).unwrap_err();
        assert_eq!(err, PlanError::DuplicateGoal { goal: "a".into() });
    }

    #[test]
    fn self_dependency_is_refused() {
        let err = plan(vec![g("a", &["a"])]).unwrap_err();
        assert_eq!(err, PlanError::SelfDependency { goal: "a".into() });
    }

    #[test]
    fn unknown_prerequisite_is_refused() {
        let err = plan(vec![g("a", &["ghost"])]).unwrap_err();
        assert_eq!(
            err,
            PlanError::UnknownPrerequisite { goal: "a".into(), prerequisite: "ghost".into() }
        );
    }

    #[test]
    fn empty_task_is_refused() {
        let err = plan(vec![GoalSpec::new("a", Vec::<String>::new(), "   ")]).unwrap_err();
        assert_eq!(err, PlanError::EmptyTask { goal: "a".into() });
    }

    #[test]
    fn a_cycle_is_reported_not_panicked() {
        let err = plan(vec![g("x", &["y"]), g("y", &["x"])]).unwrap_err();
        match err {
            PlanError::Cycle { goals } => assert_eq!(goals, vec!["x".to_string(), "y".to_string()]),
            other => panic!("expected a cycle, got {other:?}"),
        }
    }

    #[test]
    fn forward_declared_prerequisites_are_reordered_not_rejected() {
        // `d` is declared before the goals it depends on — legal input, illegal execution order.
        let plan = plan(vec![g("d", &["b", "c"]), g("b", &["a"]), g("c", &["a"]), g("a", &[])])
            .expect("diamond is a valid DAG");
        let order: Vec<&str> = plan.ordered().iter().map(|g| g.id.as_str()).collect();
        assert_eq!(order, vec!["a", "b", "c", "d"], "prerequisites must precede dependents");
    }

    #[test]
    fn duplicate_edges_do_not_strand_a_goal() {
        let plan = plan(vec![g("a", &[]), g("b", &["a", "a"])]).expect("repeated edge is harmless");
        let order: Vec<&str> = plan.ordered().iter().map(|g| g.id.as_str()).collect();
        assert_eq!(order, vec!["a", "b"]);
    }

    #[test]
    fn task_map_backend_replaces_the_goal_id_with_the_real_task() {
        struct Spy;
        impl ExecutionBackend for Spy {
            fn name(&self) -> &str {
                "spy"
            }
            fn preflight(&self, _job: &Job) -> PreflightOutcome {
                PreflightOutcome::eligible()
            }
            fn execute(&self, job: &Job) -> BackendOutcome {
                // Echo the task back so the test can assert what the backend actually received.
                BackendOutcome::completed(&job.id, "spy", job.task.clone())
            }
        }

        let goals = vec![GoalSpec::new("a", Vec::<String>::new(), "echo hello")];
        let mapped = TaskMapBackend::new(&Spy, &goals);
        let outcome = mapped.execute(&Job::new("a", "a"));
        assert_eq!(outcome.detail, "echo hello", "the declared task must reach the backend");
    }

    #[test]
    fn unknown_job_id_is_forwarded_unchanged() {
        struct Spy;
        impl ExecutionBackend for Spy {
            fn name(&self) -> &str {
                "spy"
            }
            fn execute(&self, job: &Job) -> BackendOutcome {
                BackendOutcome::completed(&job.id, "spy", job.task.clone())
            }
        }

        let goals = vec![GoalSpec::new("a", Vec::<String>::new(), "echo hello")];
        let mapped = TaskMapBackend::new(&Spy, &goals);
        let outcome = mapped.execute(&Job::new("zzz", "zzz"));
        assert_eq!(outcome.detail, "zzz", "an unmapped id must not inherit another goal's task");
    }
}
