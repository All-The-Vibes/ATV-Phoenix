//! `heal` — one bounded, logged recovery, validated by an EXTERNAL recheck (an objective sense Check).
//! Bounded (<=3 retries / one rollback) so the harness cannot loop-burn. `healed=true` only when the
//! independent recheck passes AFTER the action — recovery is proven, not asserted.

use crate::sense::{sense, Check, SenseResult};
use crate::snapshot::restore;
use serde::{Deserialize, Serialize};
use std::path::Path;

pub const MAX_RETRIES: u32 = 3;

#[derive(Debug, Clone, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Strategy {
    Retry,
    Rollback,
}

#[derive(Debug, Clone, Serialize, Deserialize, schemars::JsonSchema)]
pub struct HealCtx {
    /// Retry: argv to re-run between rechecks.
    #[serde(default)]
    pub command: Option<Vec<String>>,
    #[serde(default)]
    pub max_attempts: Option<u32>,
    /// Rollback: file to restore + the blessed snapshot id.
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default)]
    pub snap_id: Option<String>,
    /// The independent objective check that decides whether recovery actually worked.
    pub recheck: Check,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealResult {
    pub healed: bool,
    pub attempts: u32,
    pub action: String,
    pub evidence: String,
    pub recheck: SenseResult,
}

pub fn heal(workspace: &Path, strategy: Strategy, ctx: &HealCtx) -> HealResult {
    match strategy {
        Strategy::Rollback => heal_rollback(workspace, ctx),
        Strategy::Retry => heal_retry(ctx),
    }
}

fn heal_rollback(workspace: &Path, ctx: &HealCtx) -> HealResult {
    let (Some(path), Some(snap_id)) = (ctx.path.as_ref(), ctx.snap_id.as_ref()) else {
        let r = sense(&ctx.recheck);
        return HealResult {
            healed: false, attempts: 0, action: "rollback".into(),
            evidence: "rollback requires path + snap_id".into(), recheck: r,
        };
    };
    // Resolve `path` against the workspace. (join with an absolute path is a no-op, so M1's
    // absolute-path tests keep working; relative paths from MCP callers resolve correctly.)
    let p = workspace.join(path);
    let action = format!("rollback {} <- snapshot {}", path, snap_id);
    if let Err(e) = restore(workspace, &p, snap_id) {
        let r = sense(&ctx.recheck);
        return HealResult { healed: false, attempts: 1, action, evidence: format!("restore failed: {e}"), recheck: r };
    }
    // Recovery is validated by the INDEPENDENT recheck, not by the restore itself.
    let recheck = sense(&ctx.recheck);
    HealResult {
        healed: recheck.ok,
        attempts: 1,
        action,
        evidence: format!("restored {path} from {snap_id}; recheck.ok={}", recheck.ok),
        recheck,
    }
}

fn heal_retry(ctx: &HealCtx) -> HealResult {
    let cap = ctx.max_attempts.unwrap_or(MAX_RETRIES).min(MAX_RETRIES);
    let Some(cmd) = ctx.command.as_ref() else {
        let r = sense(&ctx.recheck);
        return HealResult { healed: false, attempts: 0, action: "retry".into(), evidence: "retry requires command".into(), recheck: r };
    };
    let mut last = sense(&ctx.recheck);
    let mut attempts = 0;
    while attempts < cap && !last.ok {
        attempts += 1;
        let _ = std::process::Command::new(&cmd[0]).args(&cmd[1..]).output();
        last = sense(&ctx.recheck);
    }
    HealResult {
        healed: last.ok,
        attempts,
        action: format!("retry x{attempts} (cap {cap})"),
        evidence: format!("recheck.ok={} after {attempts} attempt(s)", last.ok),
        recheck: last,
    }
}
