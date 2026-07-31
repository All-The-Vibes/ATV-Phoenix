//! `worktrees` — mandatory, exclusive worktree assignment for parallel local workers.
//!
//! #81 requires "mandatory git worktrees for parallel local workers". The word doing the work is
//! *mandatory*. Two goals building in the same checkout will interleave their edits, and the
//! resulting failure is attributed to whichever goal happened to run its tests last — a bug report
//! that points at innocent code. Worse, it is intermittent, so it survives investigation.
//!
//! This module is the assignment authority. It does not create directories; a caller does that.
//! It decides *which* path a goal owns and refuses to hand the same one to two goals, which is the
//! part worth proving without touching a filesystem.
//!
//! Two rules carry the weight:
//!
//! * **Exclusivity.** A path is assigned to at most one goal at a time. The check is on the resolved
//!   path, not the goal id, because two distinct ids can sanitise to the same directory name.
//! * **No execution without isolation.** [`WorktreeRegistry::may_execute`] answers false for a goal
//!   with no assignment. A worker that cannot prove it owns a workspace must not build in one —
//!   defaulting to "probably the repo root" is how a parallel worker corrupts the shared tree.
//!
//! Releasing is explicit and owner-checked. A goal cannot release a path it does not hold, so a
//! stale worker cannot free its replacement's workspace out from under it — the same discipline
//! [`crate::lease`] applies to fencing tokens.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Prefix for per-goal worktree directory names.
pub const WORKTREE_PREFIX: &str = "goal-";

/// Replace anything that is not alphanumeric, `-`, or `_` with `_`.
///
/// Same construction as the trace-chain filenames: `.` is excluded from the allowlist rather than
/// special-cased, so `..` cannot appear and path traversal is impossible by construction rather than
/// by argument. Collisions this creates are surfaced by [`AssignmentDenied::PathTaken`] instead of
/// silently pointing two goals at one directory.
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

/// Why a worktree could not be assigned.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AssignmentDenied {
    /// This goal already holds a worktree.
    ///
    /// Carries the existing path so an idempotent caller can proceed with what it already owns
    /// rather than treating the refusal as fatal.
    AlreadyAssigned { existing: PathBuf },
    /// Another goal holds the path this goal would resolve to.
    PathTaken { holder: String, path: PathBuf },
}

impl std::fmt::Display for AssignmentDenied {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::AlreadyAssigned { existing } => {
                write!(f, "goal already holds worktree {}", existing.display())
            }
            Self::PathTaken { holder, path } => {
                write!(f, "worktree {} is held by {holder}", path.display())
            }
        }
    }
}

impl std::error::Error for AssignmentDenied {}

/// Tracks which goal owns which worktree beneath a root directory.
#[derive(Debug, Clone)]
pub struct WorktreeRegistry {
    root: PathBuf,
    by_goal: BTreeMap<String, PathBuf>,
}

impl WorktreeRegistry {
    /// A registry handing out directories beneath `root`.
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into(), by_goal: BTreeMap::new() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// The path `goal` would resolve to, whether or not it is assigned.
    ///
    /// Pure: asking does not reserve. Callers use this to detect a collision before committing to a
    /// goal id.
    pub fn path_for(&self, goal: &str) -> PathBuf {
        self.root.join(format!("{WORKTREE_PREFIX}{}", sanitize(goal)))
    }

    /// The worktree `goal` currently owns.
    pub fn assigned(&self, goal: &str) -> Option<&Path> {
        self.by_goal.get(goal).map(PathBuf::as_path)
    }

    /// Which goal, if any, holds `path`.
    fn holder_of(&self, path: &Path) -> Option<&str> {
        self.by_goal.iter().find(|(_, p)| p.as_path() == path).map(|(g, _)| g.as_str())
    }

    /// Reserve an exclusive worktree for `goal`.
    ///
    /// Refuses if the goal already holds one, or if its resolved path belongs to another goal.
    /// Exclusivity is checked on the *path*, not the goal id, because distinct ids can sanitise to
    /// the same directory — checking ids would let a collision through unnoticed.
    pub fn assign(&mut self, goal: &str) -> Result<PathBuf, AssignmentDenied> {
        if let Some(existing) = self.by_goal.get(goal) {
            return Err(AssignmentDenied::AlreadyAssigned { existing: existing.clone() });
        }
        let path = self.path_for(goal);
        if let Some(holder) = self.holder_of(&path) {
            return Err(AssignmentDenied::PathTaken { holder: holder.to_string(), path });
        }
        self.by_goal.insert(goal.to_string(), path.clone());
        Ok(path)
    }

    /// Reserve if needed, returning the path `goal` owns either way.
    ///
    /// The idempotent form. A retry of "give this goal a workspace" must not fail merely because the
    /// first attempt succeeded, but it must still refuse a genuine collision with another goal.
    pub fn assign_or_existing(&mut self, goal: &str) -> Result<PathBuf, AssignmentDenied> {
        match self.assign(goal) {
            Ok(path) => Ok(path),
            Err(AssignmentDenied::AlreadyAssigned { existing }) => Ok(existing),
            Err(other) => Err(other),
        }
    }

    /// Release `goal`'s worktree. Returns false if it held none.
    pub fn release(&mut self, goal: &str) -> bool {
        self.by_goal.remove(goal).is_some()
    }

    /// Whether a worker for `goal` may build.
    ///
    /// False without an assignment. A worker that cannot prove it owns a workspace must not build in
    /// one; falling back to "probably the repo root" is how a parallel worker corrupts the shared
    /// tree that other work depends on.
    pub fn may_execute(&self, goal: &str) -> bool {
        self.by_goal.contains_key(goal)
    }

    /// Every current assignment, ordered by goal.
    pub fn assignments(&self) -> Vec<(&str, &Path)> {
        self.by_goal.iter().map(|(g, p)| (g.as_str(), p.as_path())).collect()
    }

    /// Whether every assigned path is distinct.
    ///
    /// An invariant check for callers and tests. It should be impossible to violate through this
    /// API; a false result means the invariant was broken elsewhere and is worth surfacing loudly
    /// rather than trusting.
    pub fn all_paths_distinct(&self) -> bool {
        let mut seen: Vec<&Path> = self.by_goal.values().map(PathBuf::as_path).collect();
        let total = seen.len();
        seen.sort_unstable();
        seen.dedup();
        seen.len() == total
    }
}
