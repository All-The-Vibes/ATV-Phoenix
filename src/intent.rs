//! `intent` — composite acceptance gate for N-goal intent manifests.
//!
//! An intent takes a high-level vague goal and decomposes it into N concrete sub-goals,
//! each with its own `phoenix_sense` acceptance check and its own per-goal trace.
//! Composite `phoenix_accept` is satisfied **only** when ALL N goals are individually proven
//! failure-first: each saw_red AND green_after_red AND currently_green on an intact trace.
//!
//! Design decisions (v1):
//! - **Trace isolation:** separate `.phoenix-intent/<id>/.phoenix/trace.jsonl` per goal.
//!   Each goal's ralph loop runs with `PHOENIX_WORKSPACE=<repo>/.phoenix-intent/<id>`.
//! - **Goal count ceiling:** MAX_GOALS = 5 (revisit after H6 data).
//! - **Independence contamination:** log warning (v1 non-fatal; v2 will enforce isolation).
//! - **Automation types:** build, integrate, configure, notify, cron, webhook — for template selection.

use crate::accept::{verify_gate, GateResult};
use crate::sense::canonical_digest;
use crate::sense::Check;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::Path;

/// Maximum number of goals per intent manifest (v1 ceiling; revisit after H6 data).
pub const MAX_GOALS: usize = 5;

/// Automation-goal kind — determines which typed acceptance-check template to apply.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum GoalKind {
    Build,
    Integrate,
    Configure,
    Notify,
    Cron,
    Webhook,
}

/// One sub-goal within an intent manifest.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoalSpec {
    /// Stable short ID (kebab-case). Used as the per-goal trace directory name.
    pub id: String,
    /// Human-readable title.
    pub title: String,
    /// The `phoenix_sense` acceptance check for this goal (must start RED at baseline).
    pub check: Check,
    /// IDs of goals that must be proven complete before this one can start (empty = independent).
    #[serde(default)]
    pub depends_on: Vec<String>,
    /// Optional automation kind for typed template selection.
    #[serde(default)]
    pub kind: Option<GoalKind>,
}

/// The top-level intent manifest (`intent.json`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntentManifest {
    /// The high-level vague intent being decomposed (human-readable).
    pub intent: String,
    /// The N concrete sub-goals (1 ≤ N ≤ MAX_GOALS).
    pub goals: Vec<GoalSpec>,
}

/// Per-goal gate result: wraps the standard GateResult with goal metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoalAcceptResult {
    pub id: String,
    pub title: String,
    pub gate: GateResult,
}

/// Composite accept result for a full intent: ALL N goals must be individually proven.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompositeAcceptResult {
    /// True only if ALL goals are individually proven failure-first and currently green.
    pub ok: bool,
    pub intent: String,
    pub goal_count: usize,
    pub goals_ok: usize,
    pub goals: Vec<GoalAcceptResult>,
    pub reason: String,
}

/// Verify composite acceptance for an intent manifest.
///
/// Each goal's trace lives at `<workspace>/.phoenix-intent/<goal_id>/.phoenix/trace.jsonl`.
/// The composite result is `ok` only if ALL goals are individually proven failure-first.
///
/// # Independence contamination (v1)
/// If two goals share the same canonical check digest, a warning is emitted to stderr.
/// This is non-fatal in v1; v2 will enforce isolation.
pub fn verify_intent(workspace: &Path, manifest: &IntentManifest) -> CompositeAcceptResult {
    // Guard: must have at least one goal.
    if manifest.goals.is_empty() {
        return CompositeAcceptResult {
            ok: false,
            intent: manifest.intent.clone(),
            goal_count: 0,
            goals_ok: 0,
            goals: vec![],
            reason: "intent has no goals".into(),
        };
    }

    // Guard: goal-count ceiling.
    if manifest.goals.len() > MAX_GOALS {
        return CompositeAcceptResult {
            ok: false,
            intent: manifest.intent.clone(),
            goal_count: manifest.goals.len(),
            goals_ok: 0,
            goals: vec![],
            reason: format!(
                "goal count {} exceeds ceiling {} — split into multiple intents or raise the \
                 ceiling after reviewing H6 data",
                manifest.goals.len(),
                MAX_GOALS
            ),
        };
    }

    // Independence-contamination check (v1: warn, not fatal).
    // Two goals with identical check digests can mask each other's failures.
    let mut seen_digests: HashSet<String> = HashSet::new();
    for goal in &manifest.goals {
        let digest = canonical_digest(&goal.check);
        if !seen_digests.insert(digest.clone()) {
            eprintln!(
                "[intent] WARNING: goals share identical check digest ({}) — \
                 independence contamination detected. A shared check can mask \
                 per-goal failures. (v1: log only; v2 will enforce isolation)",
                &digest[..16]
            );
        }
    }

    // Evaluate each goal against its per-goal trace.
    let mut goal_results: Vec<GoalAcceptResult> = Vec::new();
    for goal in &manifest.goals {
        // Per-goal workspace: <workspace>/.phoenix-intent/<goal_id>
        // Trace at: <goal_workspace>/.phoenix/trace.jsonl  (via Trace::default_in)
        let goal_ws = workspace.join(".phoenix-intent").join(&goal.id);
        let gate = verify_gate(&goal_ws, &goal.check);
        goal_results.push(GoalAcceptResult {
            id: goal.id.clone(),
            title: goal.title.clone(),
            gate,
        });
    }

    let goals_ok = goal_results.iter().filter(|g| g.gate.ok).count();
    let all_ok = goals_ok == manifest.goals.len();

    let reason = if all_ok {
        format!(
            "all {} goal(s) proven failure-first (red→green, currently green)",
            manifest.goals.len()
        )
    } else {
        let failing: Vec<&str> = goal_results
            .iter()
            .filter(|g| !g.gate.ok)
            .map(|g| g.id.as_str())
            .collect();
        format!(
            "{}/{} goal(s) not yet accepted: {:?}",
            failing.len(),
            manifest.goals.len(),
            failing
        )
    };

    CompositeAcceptResult {
        ok: all_ok,
        intent: manifest.intent.clone(),
        goal_count: manifest.goals.len(),
        goals_ok,
        goals: goal_results,
        reason,
    }
}
