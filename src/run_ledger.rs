//! `run_ledger` — durable, append-only record of what a mission actually did.
//!
//! This is the shared dependency that #80 and #81 both named. One implementation, owned here in the
//! supervisor spine because the supervisor owns run state; #80's execution backends feed it through
//! the [`crate::run_artifacts::RunArtifacts`] record rather than writing a second ledger of their
//! own. Two lanes keeping two ledgers is how a mission ends up with two different answers to "what
//! happened", and no way to tell which is right.
//!
//! **Append-only, one JSON object per line.** Rewriting history is not a supported operation: an
//! entry that can be edited is not evidence. A reader that cannot parse a line reports it as
//! unreadable rather than skipping it — silently dropping a damaged row makes a truncated ledger
//! indistinguishable from a short one, which is exactly the defect filed as #111 against the trace
//! chain. That mistake is not repeated here.
//!
//! **Crash-tolerant by construction.** A process killed mid-write leaves a partial final line. The
//! reader surfaces that as `unreadable`, so a torn tail is visible instead of quietly changing what
//! the ledger says.
//!
//! INVARIANT: the ledger is append-only. An entry that can be edited is not evidence.
//! INVARIANT: an unparseable line is reported as unreadable, never skipped. Silently dropping a
//! damaged row makes a truncated ledger indistinguishable from a short one — the #111 defect, not
//! repeated here.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::run_artifacts::{RunArtifacts, Usage};

/// Default ledger filename beneath the mission directory.
pub const LEDGER_FILE: &str = "run-ledger.jsonl";

/// One durable record of a dispatched goal.
///
/// Mirrors [`RunArtifacts`] plus the fields only the supervisor knows: which goal this was, and
/// which backend it decided to use.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LedgerEntry {
    pub goal: String,
    /// The backend the supervisor selected. Recorded even when dispatch failed, because "we chose
    /// cloud and it refused" and "we never chose" are different facts.
    pub backend: String,
    pub task_id: Option<String>,
    pub branch: Option<String>,
    pub model: Option<String>,
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub cost_micros: Option<u64>,
    pub error: Option<String>,
}

impl LedgerEntry {
    /// Build an entry for `goal` from the artifacts its dispatch produced.
    ///
    /// Optionality is carried through unchanged. A field the backend never reported stays `None`
    /// here — defaulting it to zero on the way to disk would bake "we did not measure" into "it
    /// cost nothing", permanently and unrecoverably.
    pub fn from_artifacts(goal: impl Into<String>, a: &RunArtifacts) -> Self {
        Self {
            goal: goal.into(),
            backend: a.backend.clone(),
            task_id: a.task_id.clone(),
            branch: a.branch.clone(),
            model: a.model.clone(),
            input_tokens: a.usage.input_tokens,
            output_tokens: a.usage.output_tokens,
            cost_micros: a.usage.cost_micros,
            error: a.error.clone(),
        }
    }

    /// Whether this run recorded a failure.
    pub fn failed(&self) -> bool {
        self.error.is_some()
    }

    /// Usage as reported, reusing the same "unreported is not zero" semantics.
    pub fn usage(&self) -> Usage {
        Usage {
            input_tokens: self.input_tokens,
            output_tokens: self.output_tokens,
            cost_micros: self.cost_micros,
        }
    }
}

/// What a read of the ledger found.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct LedgerRead {
    /// Entries that parsed.
    pub entries: Vec<LedgerEntry>,
    /// 0-based line numbers that could not be parsed.
    ///
    /// Reported, never skipped. A ledger that silently drops damaged rows reads as shorter rather
    /// than corrupt — the failure mode filed as #111.
    pub unreadable: Vec<usize>,
}

impl LedgerRead {
    /// Whether every line in the file parsed.
    pub fn is_intact(&self) -> bool {
        self.unreadable.is_empty()
    }

    /// Total spend across every readable entry.
    ///
    /// Sums only what was actually reported; a `None` contributes nothing rather than zero, so an
    /// unmeasured run cannot masquerade as a free one.
    pub fn total_cost_micros(&self) -> u64 {
        self.entries.iter().filter_map(|e| e.cost_micros).sum()
    }

    /// Entries recorded against `goal`.
    pub fn for_goal(&self, goal: &str) -> Vec<&LedgerEntry> {
        self.entries.iter().filter(|e| e.goal == goal).collect()
    }
}

/// Append-only run ledger for one mission.
#[derive(Debug, Clone)]
pub struct RunLedger {
    path: PathBuf,
}

impl RunLedger {
    /// A ledger at an explicit path.
    pub fn at(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    /// The mission's default ledger, at `<mission>/run-ledger.jsonl`.
    pub fn in_mission(mission_dir: &Path) -> Self {
        Self { path: mission_dir.join(LEDGER_FILE) }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Append one entry. Creates the file and parent directory if needed.
    ///
    /// Append-only: there is no update or delete. The write ends with a newline so a subsequent
    /// append cannot merge into the previous record.
    pub fn append(&self, entry: &LedgerEntry) -> std::io::Result<()> {
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let line = serde_json::to_string(entry)?;
        let mut f = OpenOptions::new().create(true).append(true).open(&self.path)?;
        writeln!(f, "{line}")
    }

    /// Convenience: record `goal`'s dispatch artifacts.
    pub fn record(&self, goal: &str, artifacts: &RunArtifacts) -> std::io::Result<()> {
        self.append(&LedgerEntry::from_artifacts(goal, artifacts))
    }

    /// Read every entry, reporting unparseable lines rather than discarding them.
    ///
    /// A missing file is an empty ledger, which is a different fact from a damaged one: the first
    /// means nothing ran, the second means we cannot say what ran.
    pub fn read(&self) -> LedgerRead {
        let Ok(content) = std::fs::read_to_string(&self.path) else {
            return LedgerRead::default();
        };
        let mut out = LedgerRead::default();
        for (i, line) in content.lines().enumerate() {
            if line.trim().is_empty() {
                continue;
            }
            match serde_json::from_str::<LedgerEntry>(line) {
                Ok(e) => out.entries.push(e),
                Err(_) => out.unreadable.push(i),
            }
        }
        out
    }
}
