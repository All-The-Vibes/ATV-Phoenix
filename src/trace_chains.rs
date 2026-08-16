//! `trace_chains` — separate hash-chained traces for the supervisor and each child goal.
//!
//! [`crate::trace`] gives one append-only chain. A mission has many concurrent writers: the
//! supervisor recording scheduling decisions, plus one Auto/Ralph loop per goal. Pointing all of
//! them at a single chain breaks the audit in two ways at once.
//!
//! **Interleaving destroys attribution.** Two children appending to one file produce rows whose
//! order reflects thread timing, not causality. Reconstructing "what did goal-2 actually do" means
//! filtering by a field and hoping nothing else wrote that field.
//!
//! **Worse, it makes tamper-evidence useless.** A chain is verified by recomputing links in order.
//! With concurrent appenders, two writers can read the same `prev_hash` and both append — the chain
//! forks, `verify()` reports broken, and a genuine tamper becomes indistinguishable from ordinary
//! concurrency. The circuit-breaker that is supposed to halt on corruption would fire constantly and
//! be switched off, which is how safety systems actually die.
//!
//! So: one chain per writer. Each goal gets its own file, the supervisor gets its own, and every
//! chain verifies independently. A corrupt child chain is contained to that child, and the
//! supervisor's own record of decisions stays intact regardless of what any worker did.
//!
//! Goal ids are sanitised into filenames because a goal id is caller-supplied and will eventually
//! contain a slash. Path traversal through an audit log's filename is not a theoretical concern.
//!
//! INVARIANT: one chain per writer. Concurrent appenders to one chain fork it, so `verify()` reports
//! broken and a genuine tamper becomes indistinguishable from ordinary concurrency — a corruption
//! alarm that fires constantly is one that gets switched off.
//! INVARIANT: every chain file resolves inside the chains directory. `.` is excluded from the
//! filename allowlist rather than special-cased, which removes the whole `..` traversal class by
//! construction instead of relying on one check being right.
//! INVARIANT: a corrupt child chain does not invalidate the supervisor's own chain or any sibling's.

use std::path::{Path, PathBuf};

use crate::trace::{Trace, TraceVerify};

/// Directory name under the workspace holding all mission chains.
pub const CHAINS_DIR: &str = ".phoenix";

/// Filename of the supervisor's own chain.
pub const SUPERVISOR_CHAIN: &str = "supervisor-trace.jsonl";

/// Replace anything that is not alphanumeric, `-`, or `_` with `_`.
///
/// A goal id is caller-supplied. Left raw, `../../etc/passwd` or `a/b` would escape the chain
/// directory or silently create nested paths.
///
/// `.` is excluded from the allowlist rather than merely handled, which removes the whole `..`
/// class by construction instead of relying on a special case being right. Collisions this creates
/// (`a.b` and `a_b`) are detectable via [`MissionChains::would_collide`] — a visible collision is a
/// far better failure than a filename whose safety depends on argument.
fn sanitize(goal: &str) -> String {
    let out: String = goal
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect();
    if out.is_empty() {
        "_".to_string()
    } else {
        out
    }
}

/// Per-writer trace chains for one mission.
#[derive(Debug, Clone)]
pub struct MissionChains {
    root: PathBuf,
}

impl MissionChains {
    /// Chains rooted at `workspace/.phoenix/`.
    pub fn in_workspace(workspace: &Path) -> Self {
        Self { root: workspace.join(CHAINS_DIR) }
    }

    /// The directory holding every chain in this mission.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Path of the supervisor's chain.
    pub fn supervisor_path(&self) -> PathBuf {
        self.root.join(SUPERVISOR_CHAIN)
    }

    /// Path of `goal`'s chain.
    pub fn goal_path(&self, goal: &str) -> PathBuf {
        self.root.join(format!("goal-{}-trace.jsonl", sanitize(goal)))
    }

    /// The supervisor's own chain, recording scheduling decisions.
    pub fn supervisor(&self) -> Trace {
        Trace::at(self.supervisor_path())
    }

    /// `goal`'s chain, recording that child loop's own sense/heal history.
    pub fn goal(&self, goal: &str) -> Trace {
        Trace::at(self.goal_path(goal))
    }

    /// Whether two goals would share a chain file.
    ///
    /// Sanitising can collide (`a/b` and `a:b` both become `a_b`), and a silent collision would
    /// merge two children's audit trails — reintroducing exactly the interleaving this module
    /// exists to prevent. A caller allocating goal ids can check first.
    pub fn would_collide(&self, a: &str, b: &str) -> bool {
        a != b && self.goal_path(a) == self.goal_path(b)
    }
}

/// Verification result for one named chain.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChainStatus {
    /// `"supervisor"` or the goal id.
    pub writer: String,
    pub ok: bool,
    pub rows: usize,
    pub broken_at: Option<usize>,
}

/// Verification across the supervisor chain and every named goal chain.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MissionVerify {
    pub supervisor: ChainStatus,
    pub goals: Vec<ChainStatus>,
}

impl MissionVerify {
    /// Whether every chain verified intact.
    pub fn all_ok(&self) -> bool {
        self.supervisor.ok && self.goals.iter().all(|g| g.ok)
    }

    /// Writers whose chain is broken.
    ///
    /// Named rather than counted: "the mission is corrupt" is not actionable, "goal-2's chain broke
    /// at row 4" is.
    pub fn broken_writers(&self) -> Vec<&str> {
        let mut out = Vec::new();
        if !self.supervisor.ok {
            out.push(self.supervisor.writer.as_str());
        }
        out.extend(self.goals.iter().filter(|g| !g.ok).map(|g| g.writer.as_str()));
        out
    }

    /// Whether the supervisor's own record survived, regardless of any child.
    ///
    /// This is the containment property: a worker that corrupts its own chain must not cost the
    /// supervisor its record of what it decided.
    pub fn supervisor_intact(&self) -> bool {
        self.supervisor.ok
    }
}

fn status(writer: &str, v: TraceVerify) -> ChainStatus {
    ChainStatus { writer: writer.to_string(), ok: v.ok, rows: v.rows, broken_at: v.broken_at }
}

/// Verify the supervisor chain plus each goal chain independently.
///
/// One broken chain never masks another: every writer is checked and reported on its own terms.
pub fn verify_mission(chains: &MissionChains, goals: &[&str]) -> MissionVerify {
    MissionVerify {
        supervisor: status("supervisor", chains.supervisor().verify()),
        goals: goals.iter().map(|g| status(g, chains.goal(g).verify())).collect(),
    }
}
