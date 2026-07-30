//! `lifecycle` — goal cancellation, supersession, and approval gating.
//!
//! The ready queue decides what runs, leases decide who owns it, budgets decide when to stop for
//! cost. This decides when a goal stops for *intent*: the operator cancelled it, a newer revision
//! replaced it, or it is parked waiting for a human.
//!
//! The property that carries the weight is **terminality**. Once a goal reaches `Completed`,
//! `Cancelled`, `Superseded`, or `Failed`, nothing may move it again. A supervisor that can revive a
//! cancelled goal has no cancellation at all — it has a suggestion. Every transition is therefore
//! checked against the current state and refused with a reason rather than silently ignored, because
//! a silently-dropped cancellation looks identical to a cancellation that worked.
//!
//! Supersession carries the replacement's identity. "This goal was superseded" is not actionable on
//! its own; "superseded by revision 7" lets the supervisor find the work that took over, and lets an
//! audit answer why a goal stopped without inferring it from timing.
//!
//! No clock and no I/O — pure state, same discipline as the rest of the supervisor spine.

use std::collections::BTreeMap;

/// Where a goal is in its life.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GoalState {
    /// Admitted and executing.
    Running,
    /// Parked until a human approves. Still live: it can be cancelled or superseded from here.
    AwaitingApproval,
    /// Finished successfully. Terminal.
    Completed,
    /// Stopped on operator intent. Terminal.
    Cancelled { reason: String },
    /// Replaced by another goal. Terminal.
    Superseded { by: String },
    /// Stopped because the work itself failed. Terminal.
    Failed { reason: String },
}

impl GoalState {
    /// Whether this state can never change again.
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Cancelled { .. } | Self::Superseded { .. } | Self::Failed { .. }
        )
    }

    /// Whether the goal is still doing or waiting to do work.
    pub fn is_live(&self) -> bool {
        !self.is_terminal()
    }

    /// Whether a worker holding this goal should keep going.
    ///
    /// `AwaitingApproval` is live but must not execute — conflating "not finished" with "keep
    /// working" is how a goal runs straight through the gate it was parked at.
    pub fn should_execute(&self) -> bool {
        matches!(self, Self::Running)
    }
}

/// Why a transition was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TransitionDenied {
    /// The goal is already terminal; its outcome is fixed.
    AlreadyTerminal { current: GoalState },
    /// The goal is not tracked at all.
    UnknownGoal,
    /// A goal cannot supersede itself — that would make it its own replacement and orphan the work.
    SelfSupersession,
}

impl std::fmt::Display for TransitionDenied {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::AlreadyTerminal { .. } => f.write_str("goal already reached a terminal state"),
            Self::UnknownGoal => f.write_str("goal is not tracked"),
            Self::SelfSupersession => f.write_str("a goal cannot supersede itself"),
        }
    }
}

impl std::error::Error for TransitionDenied {}

/// Tracks the lifecycle state of every goal in a mission.
#[derive(Debug, Clone, Default)]
pub struct Lifecycle {
    states: BTreeMap<String, GoalState>,
}

impl Lifecycle {
    pub fn new() -> Self {
        Self::default()
    }

    /// Begin tracking `goal` as running. Re-admitting an existing goal does not reset it.
    ///
    /// Returning the existing state rather than overwriting matters: an idempotent retry of "start
    /// this goal" must not resurrect one that was cancelled while the retry was in flight.
    pub fn admit(&mut self, goal: &str) -> GoalState {
        self.states.entry(goal.to_string()).or_insert(GoalState::Running).clone()
    }

    /// Current state of `goal`, if tracked.
    pub fn state(&self, goal: &str) -> Option<&GoalState> {
        self.states.get(goal)
    }

    /// Whether a worker holding `goal` should keep executing.
    ///
    /// An untracked goal answers `false`: a worker that cannot find its own goal has no mandate.
    pub fn should_execute(&self, goal: &str) -> bool {
        self.states.get(goal).is_some_and(GoalState::should_execute)
    }

    fn transition(&mut self, goal: &str, next: GoalState) -> Result<GoalState, TransitionDenied> {
        match self.states.get(goal) {
            None => Err(TransitionDenied::UnknownGoal),
            Some(current) if current.is_terminal() => {
                Err(TransitionDenied::AlreadyTerminal { current: current.clone() })
            }
            Some(_) => {
                self.states.insert(goal.to_string(), next.clone());
                Ok(next)
            }
        }
    }

    /// Cancel `goal` on operator intent.
    pub fn cancel(&mut self, goal: &str, reason: impl Into<String>) -> Result<GoalState, TransitionDenied> {
        self.transition(goal, GoalState::Cancelled { reason: reason.into() })
    }

    /// Mark `goal` replaced by `replacement`.
    ///
    /// The replacement is recorded so the supervisor can follow the work, and an audit can answer
    /// "what took over" without inferring it from timestamps.
    pub fn supersede(&mut self, goal: &str, replacement: &str) -> Result<GoalState, TransitionDenied> {
        if goal == replacement {
            return Err(TransitionDenied::SelfSupersession);
        }
        self.transition(goal, GoalState::Superseded { by: replacement.to_string() })
    }

    /// Park `goal` until a human approves.
    pub fn await_approval(&mut self, goal: &str) -> Result<GoalState, TransitionDenied> {
        self.transition(goal, GoalState::AwaitingApproval)
    }

    /// Resume a parked goal.
    ///
    /// Refused once terminal, so an approval that lands after a cancellation cannot revive the goal.
    pub fn approve(&mut self, goal: &str) -> Result<GoalState, TransitionDenied> {
        self.transition(goal, GoalState::Running)
    }

    pub fn complete(&mut self, goal: &str) -> Result<GoalState, TransitionDenied> {
        self.transition(goal, GoalState::Completed)
    }

    pub fn fail(&mut self, goal: &str, reason: impl Into<String>) -> Result<GoalState, TransitionDenied> {
        self.transition(goal, GoalState::Failed { reason: reason.into() })
    }

    /// Goals that are tracked but no longer live — the orphan-cleanup worklist.
    pub fn terminal_goals(&self) -> Vec<&str> {
        self.states
            .iter()
            .filter(|(_, s)| s.is_terminal())
            .map(|(g, _)| g.as_str())
            .collect()
    }

    /// Goals still running or awaiting approval.
    pub fn live_goals(&self) -> Vec<&str> {
        self.states.iter().filter(|(_, s)| s.is_live()).map(|(g, _)| g.as_str()).collect()
    }
}
