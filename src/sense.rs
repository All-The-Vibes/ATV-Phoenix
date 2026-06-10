//! `sense` — objective failure detection. No LLM, no opinion. `ok=false` is honest, not a failure.

use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::Command;
use std::time::Instant;

const MAX_EVIDENCE: usize = 2048;

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
    pub target: Vec<String>,
    /// CommandExit: expected exit code as string (default "0"). FileSha256: expected hex digest.
    /// RegexInFile: the regex pattern.
    #[serde(default)]
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
