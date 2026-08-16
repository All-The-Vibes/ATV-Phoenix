//! `budget` — per-goal and mission-wide time, token, and retry budgets.
//!
//! The supervisor's ready queue decides *what* runs and leases decide *who owns it*. Budgets decide
//! *when to stop* — the guard against a mission that is technically making progress but has already
//! spent more than the outcome is worth.
//!
//! Two levels, checked together. A goal can exhaust its own allowance while the mission still has
//! room (that goal stops, others continue), or the mission can run dry while an individual goal
//! still looks fine (everything stops). Charging a goal therefore always charges the mission too;
//! keeping two independent counters that could disagree would let spend escape one of them.
//!
//! Time is a caller-supplied logical clock, matching the ready queue and lease registry — the same
//! call sequence always produces the same verdicts, so a budget test can never flake.
//!
//! Design stance worth stating: **an unset limit means unlimited, and every limit is opt-in.** The
//! alternative — defaulting to some "sensible" number — would silently cap missions nobody asked to
//! cap, and the failure would look like a mysterious halt rather than a policy decision.
//!
//! INVARIANT: charging a goal always charges the mission too. Two independent counters that could
//! disagree would let spend escape one of them, which is the whole failure budgets exist to prevent.
//! INVARIANT: a refusal names both the scope and the resource. `Goal`+`Tokens` means abandon this
//! goal and continue; `Mission`+`Tokens` means stop everything — collapsing them forces the
//! supervisor to guess.
//! INVARIANT: an unset limit never refuses.

use std::collections::BTreeMap;

/// Which allowance ran out.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Resource {
    Time,
    Tokens,
    Retries,
}

/// Which level of the hierarchy refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scope {
    Goal,
    Mission,
}

/// A refusal to continue, naming the level and the resource.
///
/// Both fields matter to a caller: `Goal`+`Tokens` means "abandon this goal, the mission can go on",
/// while `Mission`+`Tokens` means "stop everything". Collapsing them into one error would force the
/// supervisor to guess.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BudgetExceeded {
    pub scope: Scope,
    pub resource: Resource,
}

impl std::fmt::Display for BudgetExceeded {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let scope = match self.scope {
            Scope::Goal => "goal",
            Scope::Mission => "mission",
        };
        let resource = match self.resource {
            Resource::Time => "time",
            Resource::Tokens => "tokens",
            Resource::Retries => "retries",
        };
        write!(f, "{scope} {resource} budget exhausted")
    }
}

impl std::error::Error for BudgetExceeded {}

/// An allowance. `None` on any field means that resource is unlimited.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Limits {
    /// Logical time units this scope may consume in total.
    pub time: Option<u64>,
    pub tokens: Option<u64>,
    /// Retries allowed. A limit of 0 means the first attempt is all there is.
    pub retries: Option<u32>,
}

impl Limits {
    /// No limits at all.
    pub fn unlimited() -> Self {
        Self::default()
    }

    pub fn with_time(mut self, time: u64) -> Self {
        self.time = Some(time);
        self
    }

    pub fn with_tokens(mut self, tokens: u64) -> Self {
        self.tokens = Some(tokens);
        self
    }

    pub fn with_retries(mut self, retries: u32) -> Self {
        self.retries = Some(retries);
        self
    }
}

/// Running totals for one scope.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Spend {
    pub time: u64,
    pub tokens: u64,
    pub retries: u32,
}

impl Spend {
    /// Whether adding `amount` to `used` would exceed `limit`.
    ///
    /// Overflow counts as exceeding even when no limit is set: a total the counter cannot represent
    /// is not affordable, and recording a wrapped value would understate real spend forever.
    ///
    /// `checked_add`, not `saturating_add` — saturation silently clamps to `u64::MAX`, which then
    /// compares as *within* a `u64::MAX` limit. That reads an overflow as affordable, which is the
    /// exact failure this guard exists to prevent.
    fn would_exceed_u64(used: u64, amount: u64, limit: Option<u64>) -> bool {
        match used.checked_add(amount) {
            None => true,
            Some(total) => match limit {
                None => false,
                Some(max) => total > max,
            },
        }
    }

    fn would_exceed_u32(used: u32, amount: u32, limit: Option<u32>) -> bool {
        match used.checked_add(amount) {
            None => true,
            Some(total) => match limit {
                None => false,
                Some(max) => total > max,
            },
        }
    }
}

/// Tracks spend against per-goal and mission-wide limits.
#[derive(Debug, Clone)]
pub struct BudgetLedger {
    mission_limits: Limits,
    mission_spend: Spend,
    goal_limits: Limits,
    goal_spend: BTreeMap<String, Spend>,
}

impl BudgetLedger {
    /// Build a ledger where every goal shares the same per-goal allowance.
    pub fn new(mission_limits: Limits, goal_limits: Limits) -> Self {
        Self {
            mission_limits,
            mission_spend: Spend::default(),
            goal_limits,
            goal_spend: BTreeMap::new(),
        }
    }

    /// Spend recorded against `goal` so far.
    pub fn goal_spend(&self, goal: &str) -> Spend {
        self.goal_spend.get(goal).copied().unwrap_or_default()
    }

    /// Total spend across the mission.
    pub fn mission_spend(&self) -> Spend {
        self.mission_spend
    }

    /// Would charging `goal` for `tokens` be refused, and by whom?
    ///
    /// The goal is checked first so a caller learns the *narrowest* reason to stop: if this goal is
    /// out of budget but the mission is not, only this goal needs to end.
    pub fn check_tokens(&self, goal: &str, tokens: u64) -> Result<(), BudgetExceeded> {
        let used = self.goal_spend(goal);
        if Spend::would_exceed_u64(used.tokens, tokens, self.goal_limits.tokens) {
            return Err(BudgetExceeded { scope: Scope::Goal, resource: Resource::Tokens });
        }
        if Spend::would_exceed_u64(self.mission_spend.tokens, tokens, self.mission_limits.tokens) {
            return Err(BudgetExceeded { scope: Scope::Mission, resource: Resource::Tokens });
        }
        Ok(())
    }

    /// Charge `tokens` to `goal` and the mission, or refuse without recording anything.
    ///
    /// Refusal leaves both counters untouched: a rejected charge that still moved the totals would
    /// make the ledger drift from what was actually spent.
    pub fn charge_tokens(&mut self, goal: &str, tokens: u64) -> Result<(), BudgetExceeded> {
        self.check_tokens(goal, tokens)?;
        self.goal_spend.entry(goal.to_string()).or_default().tokens += tokens;
        self.mission_spend.tokens += tokens;
        Ok(())
    }

    /// Charge elapsed logical time to `goal` and the mission.
    pub fn charge_time(&mut self, goal: &str, elapsed: u64) -> Result<(), BudgetExceeded> {
        let used = self.goal_spend(goal);
        if Spend::would_exceed_u64(used.time, elapsed, self.goal_limits.time) {
            return Err(BudgetExceeded { scope: Scope::Goal, resource: Resource::Time });
        }
        if Spend::would_exceed_u64(self.mission_spend.time, elapsed, self.mission_limits.time) {
            return Err(BudgetExceeded { scope: Scope::Mission, resource: Resource::Time });
        }
        self.goal_spend.entry(goal.to_string()).or_default().time += elapsed;
        self.mission_spend.time += elapsed;
        Ok(())
    }

    /// Record one retry of `goal`.
    ///
    /// A per-goal retry limit of 0 means the first attempt is the only one — the first retry is
    /// already over budget.
    pub fn charge_retry(&mut self, goal: &str) -> Result<(), BudgetExceeded> {
        let used = self.goal_spend(goal);
        if Spend::would_exceed_u32(used.retries, 1, self.goal_limits.retries) {
            return Err(BudgetExceeded { scope: Scope::Goal, resource: Resource::Retries });
        }
        if Spend::would_exceed_u32(self.mission_spend.retries, 1, self.mission_limits.retries) {
            return Err(BudgetExceeded { scope: Scope::Mission, resource: Resource::Retries });
        }
        self.goal_spend.entry(goal.to_string()).or_default().retries += 1;
        self.mission_spend.retries += 1;
        Ok(())
    }

    /// Whether `goal` still has room under every one of its own limits.
    ///
    /// Deliberately excludes the mission level: a caller asking "can this goal do more?" is asking
    /// about the goal. Mission exhaustion is a separate, louder question.
    pub fn goal_has_room(&self, goal: &str) -> bool {
        let used = self.goal_spend(goal);
        !Spend::would_exceed_u64(used.time, 1, self.goal_limits.time)
            && !Spend::would_exceed_u64(used.tokens, 1, self.goal_limits.tokens)
            && !Spend::would_exceed_u32(used.retries, 1, self.goal_limits.retries)
    }
}
