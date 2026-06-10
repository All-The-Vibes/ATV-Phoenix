//! `trace` — append-only, hash-chained, tamper-EVIDENT event log (not tamper-proof).
//! Same chaining scheme proven in the goose scorecard: hash = sha256(prev_hash + canonical_row_without_hash).

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const GENESIS: &str = "GENESIS";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceEvent {
    pub ts: String,
    pub tool: String,
    pub input_digest: String,
    pub ok: bool,
    pub signal: String,
    pub evidence: String,
    pub prev_hash: String,
    pub hash: String,
}

pub struct Trace {
    path: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceVerify {
    pub ok: bool,
    pub rows: usize,
    pub head_hash: String,
    pub broken_at: Option<usize>,
}

fn now_ts() -> String {
    // Monotonic-ish wall clock without extra deps: seconds since epoch.
    let d = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!("{}.{:09}", d.as_secs(), d.subsec_nanos())
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

/// Canonical body hash over every field EXCEPT `hash` and `prev_hash`, prefixed by prev_hash.
fn row_hash(ev: &TraceEvent) -> String {
    let body = serde_json::json!({
        "ts": ev.ts, "tool": ev.tool, "input_digest": ev.input_digest,
        "ok": ev.ok, "signal": ev.signal, "evidence": ev.evidence,
    });
    let canonical = serde_json::to_string(&body).unwrap_or_default();
    let mut h = Sha256::new();
    h.update(ev.prev_hash.as_bytes());
    h.update(canonical.as_bytes());
    hex(&h.finalize())
}

impl Trace {
    pub fn at(path: PathBuf) -> Self {
        Trace { path }
    }

    pub fn default_in(workspace: &Path) -> Self {
        Trace { path: workspace.join(".phoenix").join("trace.jsonl") }
    }

    fn last_hash(&self) -> String {
        let Ok(content) = std::fs::read_to_string(&self.path) else { return GENESIS.into() };
        content
            .lines()
            .filter(|l| !l.trim().is_empty())
            .last()
            .and_then(|l| serde_json::from_str::<TraceEvent>(l).ok())
            .map(|e| e.hash)
            .unwrap_or_else(|| GENESIS.into())
    }

    /// Append one hash-chained event. `input_digest` is sha256 of the tool input for replay/audit.
    pub fn append(&self, tool: &str, input_digest: &str, ok: bool, signal: &str, evidence: &str) -> std::io::Result<TraceEvent> {
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let prev_hash = self.last_hash();
        let mut ev = TraceEvent {
            ts: now_ts(),
            tool: tool.to_string(),
            input_digest: input_digest.to_string(),
            ok,
            signal: signal.to_string(),
            evidence: evidence.to_string(),
            prev_hash,
            hash: String::new(),
        };
        ev.hash = row_hash(&ev);
        let mut f = std::fs::OpenOptions::new().create(true).append(true).open(&self.path)?;
        writeln!(f, "{}", serde_json::to_string(&ev)?)?;
        Ok(ev)
    }

    pub fn read_all(&self) -> Vec<TraceEvent> {
        let Ok(content) = std::fs::read_to_string(&self.path) else { return vec![] };
        content
            .lines()
            .filter(|l| !l.trim().is_empty())
            .filter_map(|l| serde_json::from_str::<TraceEvent>(l).ok())
            .collect()
    }

    /// Recompute the chain; tamper-EVIDENT: any edited row breaks linkage or hash.
    pub fn verify(&self) -> TraceVerify {
        let rows = self.read_all();
        let mut prev = GENESIS.to_string();
        for (i, ev) in rows.iter().enumerate() {
            if ev.prev_hash != prev || row_hash(ev) != ev.hash {
                return TraceVerify { ok: false, rows: rows.len(), head_hash: prev, broken_at: Some(i) };
            }
            prev = ev.hash.clone();
        }
        TraceVerify { ok: true, rows: rows.len(), head_hash: prev, broken_at: None }
    }
}

pub fn digest_str(s: &str) -> String {
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    hex(&h.finalize())
}

pub fn ts() -> String {
    now_ts()
}
