//! `sense` — objective failure detection. No LLM, no opinion. `ok=false` is honest, not a failure.

use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::Command;
use std::time::Instant;

const MAX_EVIDENCE: usize = 2048;

/// Accept `target` as a JSON array of strings OR a single string. A lone string is split on
/// whitespace into argv (so "cmd /C findstr x" works), matching how LLMs sometimes pass commands.
fn de_string_or_vec<'de, D>(d: D) -> Result<Vec<String>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::Deserialize;
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum VecOrStr {
        V(Vec<String>),
        S(String),
    }
    Ok(match VecOrStr::deserialize(d)? {
        VecOrStr::V(v) => v,
        VecOrStr::S(s) => s.split_whitespace().map(|x| x.to_string()).collect(),
    })
}

/// Accept `expect` as a JSON string, number, or null — LLM callers often pass an exit code as `0`
/// rather than `"0"`. Normalizes everything to `Option<String>`.
fn de_string_or_number<'de, D>(d: D) -> Result<Option<String>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::Deserialize;
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum StrOrNum {
        S(String),
        I(i64),
        F(f64),
        Null,
    }
    Ok(match Option::<StrOrNum>::deserialize(d)? {
        None | Some(StrOrNum::Null) => None,
        Some(StrOrNum::S(s)) => Some(s),
        Some(StrOrNum::I(i)) => Some(i.to_string()),
        Some(StrOrNum::F(f)) => Some(f.to_string()),
    })
}

#[derive(Debug, Clone, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CheckKind {
    /// Run `target` as argv (no shell); pass iff exit code == expect (default 0).
    CommandExit,
    /// Pass iff sha256(file at target) == expect.
    FileSha256,
    /// Pass iff regex `expect` matches the contents of file `target`.
    RegexInFile,
}

#[derive(Debug, Clone, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Check {
    pub kind: CheckKind,
    /// For CommandExit: argv (first element is the program). For file checks: a single path.
    /// Accepts a JSON array OR a single string (a lone string becomes a one-element argv), because
    /// LLM callers sometimes pass a command as a string.
    #[serde(deserialize_with = "de_string_or_vec")]
    pub target: Vec<String>,
    /// CommandExit: expected exit code (default "0"). FileSha256: expected hex digest.
    /// RegexInFile: the regex pattern. Accepts a string OR a number (e.g. `0` or `"0"`),
    /// because LLM callers naturally pass exit codes as integers.
    #[serde(default, deserialize_with = "de_string_or_number")]
    pub expect: Option<String>,
    /// Optional working directory / timeout for CommandExit.
    #[serde(default)]
    pub cwd: Option<String>,
    #[serde(default)]
    pub timeout_secs: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SenseResult {
    pub ok: bool,
    pub signal: String,
    pub evidence: String,
}

fn truncate(mut s: String) -> String {
    if s.len() > MAX_EVIDENCE {
        s.truncate(MAX_EVIDENCE);
        s.push_str("…[truncated]");
    }
    s
}

pub fn sha256_file(path: &Path) -> std::io::Result<String> {
    use sha2::{Digest, Sha256};
    let bytes = std::fs::read(path)?;
    let mut h = Sha256::new();
    h.update(&bytes);
    Ok(hex(&h.finalize()))
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

pub fn sense(check: &Check) -> SenseResult {
    match check.kind {
        CheckKind::CommandExit => sense_command(check),
        CheckKind::FileSha256 => sense_sha256(check),
        CheckKind::RegexInFile => sense_regex(check),
    }
}

/// Stable identity digest of a check — IDENTICAL in the MCP path, the CLI path, and the gate ledger,
/// so one logical check is uniquely findable across the trace. Hashes the *parsed* check (kind,
/// target, normalized expect), not the raw input bytes, so a command passed as `"pytest -q"` or
/// `["pytest","-q"]`, or an exit code as `0` or `"0"`, all digest the same. `cwd`/`timeout` are
/// execution context, not check identity, so they're excluded. This is the key that lets
/// `accept` prove a specific check went red→green (see `crate::accept`).
pub fn canonical_digest(check: &Check) -> String {
    use sha2::{Digest, Sha256};
    let expect = match (&check.kind, &check.expect) {
        (CheckKind::CommandExit, None) => Some("0".to_string()),
        (_, e) => e.clone(),
    };
    // Gate-script integrity (issue #14): for command_exit where target[0] is an existing file
    // (a gate script like "node scripts/verify.mjs" or "python verify.py"), fold the file's
    // sha256 into the digest. Any edit to the script changes the digest, so old trace events
    // (red observations) no longer match the new check, and accept correctly rejects it.
    // Bare binary names on PATH (e.g. "python", "cargo") are not files in cwd — unaffected.
    let script_hash: Option<String> = match check.kind {
        CheckKind::CommandExit if !check.target.is_empty() => {
            let p = std::path::Path::new(&check.target[0]);
            if p.is_file() { sha256_file(p).ok() } else { None }
        }
        _ => None,
    };
    let canonical = serde_json::json!({
        "kind": check.kind,
        "target": check.target,
        "expect": expect,
        "script_hash": script_hash,
    });
    let s = serde_json::to_string(&canonical).unwrap_or_default();
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    hex(&h.finalize())
}

fn sense_command(check: &Check) -> SenseResult {
    if check.target.is_empty() {
        return SenseResult { ok: false, signal: "command_exit".into(), evidence: "empty argv".into() };
    }
    let expect: i32 = check.expect.as_deref().unwrap_or("0").parse().unwrap_or(0);
    let started = Instant::now();
    let mut cmd = Command::new(&check.target[0]);
    cmd.args(&check.target[1..]);
    if let Some(dir) = &check.cwd {
        cmd.current_dir(dir);
    }
    // argv-only, no shell. (v0: timeout enforced by caller-side test harness; documented limitation.)
    match cmd.output() {
        Ok(out) => {
            let code = out.status.code().unwrap_or(-1);
            let ok = code == expect;
            let tail = String::from_utf8_lossy(if out.stderr.is_empty() { &out.stdout } else { &out.stderr });
            SenseResult {
                ok,
                signal: "command_exit".into(),
                evidence: truncate(format!(
                    "argv={:?} exit={} expect={} ({}ms)\n{}",
                    check.target, code, expect, started.elapsed().as_millis(), tail
                )),
            }
        }
        Err(e) => SenseResult {
            ok: false,
            signal: "command_exit".into(),
            evidence: truncate(format!("spawn failed: {e}")),
        },
    }
}

fn sense_sha256(check: &Check) -> SenseResult {
    let path = Path::new(&check.target[0]);
    match sha256_file(path) {
        Ok(got) => {
            let want = check.expect.clone().unwrap_or_default();
            SenseResult {
                ok: got == want,
                signal: "file_sha256".into(),
                evidence: format!("path={} got={} want={}", path.display(), got, want),
            }
        }
        Err(e) => SenseResult {
            ok: false,
            signal: "file_sha256".into(),
            evidence: format!("read {} failed: {e}", path.display()),
        },
    }
}

fn sense_regex(check: &Check) -> SenseResult {
    let path = Path::new(&check.target[0]);
    let pat = check.expect.clone().unwrap_or_default();
    let re = match regex::Regex::new(&pat) {
        Ok(r) => r,
        Err(e) => return SenseResult { ok: false, signal: "regex_in_file".into(), evidence: format!("bad regex: {e}") },
    };
    match std::fs::read_to_string(path) {
        Ok(contents) => SenseResult {
            ok: re.is_match(&contents),
            signal: "regex_in_file".into(),
            evidence: format!("path={} pattern={}", path.display(), pat),
        },
        Err(e) => SenseResult { ok: false, signal: "regex_in_file".into(), evidence: format!("read failed: {e}") },
    }
}

#[cfg(test)]
mod expect_flex {
    use super::*;
    #[test]
    fn expect_accepts_int_or_string_or_null() {
        // integer (LLM-style)
        let c: Check = serde_json::from_str(r#"{"kind":"command_exit","target":["x"],"expect":0}"#).unwrap();
        assert_eq!(c.expect.as_deref(), Some("0"));
        // string
        let c: Check = serde_json::from_str(r#"{"kind":"command_exit","target":["x"],"expect":"0"}"#).unwrap();
        assert_eq!(c.expect.as_deref(), Some("0"));
        // absent
        let c: Check = serde_json::from_str(r#"{"kind":"command_exit","target":["x"]}"#).unwrap();
        assert_eq!(c.expect, None);
    }
}

#[cfg(test)]
mod target_flex {
    use super::*;
    #[test]
    fn target_accepts_array_or_string() {
        let c: Check = serde_json::from_str(r#"{"kind":"command_exit","target":["pytest","-q"]}"#).unwrap();
        assert_eq!(c.target, vec!["pytest","-q"]);
        let c: Check = serde_json::from_str(r#"{"kind":"command_exit","target":"cmd /C findstr x f.txt"}"#).unwrap();
        assert_eq!(c.target, vec!["cmd","/C","findstr","x","f.txt"]);
    }
}
