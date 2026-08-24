//! `sense` — objective failure detection. No LLM, no opinion. `ok=false` is honest, not a failure.
//!
//! INVARIANT: a `CommandExit` result's measured elapsed time does not exceed its declared
//! `timeout_secs`. This is the #203 defect stated as a property: the field was in the public MCP
//! schema and read nowhere, so a check declaring a 2-second bound returned GREEN after 14,505 ms.
//! INVARIANT: `timed_out` and `exit_code` are independent facts. A process can time out AND exit 0
//! because it trapped the signal, so `exit_code` is `None` on a kill rather than a `-1` sentinel
//! that a genuine exit of `-1` is indistinguishable from.
//! INVARIANT: evidence truncation never panics and keeps the tail. Subprocess output is arbitrary
//! bytes, so slicing at a fixed offset aborts the arbiter data-dependently, and only ever while a
//! check is already failing; the diagnosis lives at the end, the collection banner at the start.
//! INVARIANT: `canonical_digest` is identical for one logical check across the MCP path, the CLI
//! path, and the gate ledger — it hashes the parsed check, so `"pytest -q"` and `["pytest","-q"]`
//! agree, and it folds every named file so editing a gate script moves the digest.

use serde::{Deserialize, Serialize};
use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

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

#[derive(Debug, Clone, Default, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
#[schemars(inline)]
pub enum CheckKind {
    /// Run `target` as argv (no shell); pass iff exit code == expect (default 0).
    ///
    /// Default variant. A default-constructed `Check` has an empty `target`, and #217 made every
    /// kind read RED on an empty target, so the default cannot be mistaken for a passing check.
    #[default]
    CommandExit,
    /// Pass iff sha256(file at target) == expect.
    FileSha256,
    /// Pass iff regex `expect` matches the contents of file `target`.
    RegexInFile,
    /// Pass iff the prompt surface recorded in the baseline manifest at `target[0]` is unchanged
    /// (no added / removed / changed files). RED on any drift. `target = [baseline_manifest_path]`.
    PromptManifest,
    /// Run `target[0]` with node (plus any args in target[1..]), parse `{"ok":bool}` from stdout.
    /// Used with verify-ui.mjs or any --json behavioral gate. Pass iff ok=true in output.
    UiBehavior,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, schemars::JsonSchema)]
#[schemars(inline)]
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
    /// Files this check depends on that it does not name in `target` (#211).
    ///
    /// `canonical_digest` folds the sha256 of every file in `target`, so editing a test file the
    /// check names moves the digest and any recorded RED stops binding. It cannot see what that
    /// file imports: a helper module, a fixture, the module actually under test. Those move
    /// underneath a recorded GREEN and the GREEN keeps asserting a world that no longer exists.
    /// Under `phoenix-mission` that is not hypothetical, because a sibling goal landing a commit
    /// is exactly this case, and `depends_on` says so up front.
    ///
    /// Declaring a path here folds it into the identity, so the check goes stale when it moves.
    /// Absent or empty leaves the digest byte-identical to a pre-#211 check, so every recorded
    /// trace event stays valid.
    #[serde(default)]
    pub inputs: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SenseResult {
    pub ok: bool,
    /// The check kind that produced this result (`command_exit`, `file_sha256`, ...). Not a POSIX
    /// signal number — see `killed_by_signal` for that.
    pub signal: String,
    pub evidence: String,
    /// True when the command was killed because it outlived `timeout_secs`.
    ///
    /// Reported as its own fact rather than folded into the exit code, because a result can be
    /// several things at once: a process can time out AND exit 0 because it trapped the signal.
    /// Collapsing them lets a caller read a cut-short run as a clean success.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub timed_out: bool,
    /// The process exit code, when it exited normally. `None` when it was killed by a signal or by
    /// the deadline — which is why this is an `Option` rather than the old `-1` sentinel that was
    /// indistinguishable from a genuine exit of `-1`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub exit_code: Option<i32>,
}

/// Trim `s` to fit `MAX_EVIDENCE`, keeping the **tail**.
///
/// Two properties this must hold, both learned the hard way:
///
/// 1. **Never panic.** `String::truncate` asserts its index is a UTF-8 char boundary, and subprocess
///    output is arbitrary bytes — pytest and rich draw box characters, cargo emits arrows, test
///    names and paths carry non-ASCII. Slicing at a fixed byte offset aborts the arbiter, and
///    whether it does is data-dependent, so it fails intermittently and only when a check is
///    already failing.
/// 2. **Keep the tail.** Test runners put the failure summary, the assertion diff and the final
///    error at the end. Keeping the head preserves collection banners and discards the diagnosis.
fn truncate(s: String) -> String {
    if s.len() <= MAX_EVIDENCE {
        return s;
    }
    const MARKER: &str = "[truncated, showing tail]\n";
    // Walk forward to the next char boundary so the split never lands inside a character.
    let mut start = s.len() - MAX_EVIDENCE.min(s.len());
    while start < s.len() && !s.is_char_boundary(start) {
        start += 1;
    }
    let mut out = String::with_capacity(MARKER.len() + (s.len() - start));
    out.push_str(MARKER);
    out.push_str(&s[start..]);
    out
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
        CheckKind::PromptManifest => sense_prompt_manifest(check),
        CheckKind::UiBehavior => sense_ui_behavior(check),
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
    // Gate integrity (issues #14, #146): for command_exit, fold the sha256 of every target
    // element that is an existing file into the digest, in target order and tagged with its
    // argv position. This pins the files named directly in the check: a gate script at
    // target[0] like "python verify.py", and test or script files named later in argv, so
    // ["python","-m","pytest","tests/test_x.py"] pins tests/test_x.py and
    // ["node","scripts/verify.mjs"] pins scripts/verify.mjs. Editing any pinned file changes
    // the digest, so old trace events (red observations) no longer match the new check and
    // accept correctly rejects it. What is pinned is exactly the files named in target;
    // anything they import, such as a helper module a test pulls in, is not pinned. Bare
    // binary names on PATH ("python", "cargo") and flags ("-q", "--locked") are not files, so
    // they contribute nothing. A check that names no files digests as it did before this change.
    let file_hashes: Vec<serde_json::Value> = match check.kind {
        CheckKind::CommandExit => check
            .target
            .iter()
            .enumerate()
            .filter_map(|(index, argument)| {
                let p = std::path::Path::new(argument);
                if p.is_file() {
                    // Tolerant like the pre-#146 code: an unreadable file folds nothing
                    // rather than panicking. The argv index is part of the folded value so
                    // moving a filename to a different position changes the digest.
                    sha256_file(p).ok().map(|h| serde_json::json!([index, h]))
                } else {
                    None
                }
            })
            .collect(),
        _ => Vec::new(),
    };
    // An empty collection serializes to null, identical to the pre-#146 no-file digest, so a
    // check that names no files keeps its old identity. A non-empty list of [position, sha256]
    // pairs makes both the file bytes and the argv position part of the check identity.
    let script_hash = if file_hashes.is_empty() {
        serde_json::Value::Null
    } else {
        serde_json::Value::Array(file_hashes)
    };
    // #211 — fold declared transitive inputs. `script_hash` above pins only the files named in
    // `target`; anything they import is invisible to it, so a GREEN keeps binding after a helper
    // module or the module under test moves. `inputs` is where a check declares those, and folding
    // them makes the digest go stale exactly when they do.
    //
    // Sorted by path, because `inputs` is a set of dependencies rather than an ordered argv:
    // reordering a declaration does not change what the check depends on, so it must not change
    // the check's identity. Tagged by path for the same reason, where `script_hash` tags by argv
    // index. A missing declared input folds the empty string rather than nothing, so deleting a
    // file a check depends on moves the digest instead of silently reading like it was never
    // declared.
    let input_hashes: Vec<serde_json::Value> = {
        let mut paths: Vec<&String> = check.inputs.iter().collect();
        paths.sort();
        paths.dedup();
        paths
            .into_iter()
            .map(|declared| {
                let p = std::path::Path::new(declared);
                let h = if p.is_file() { sha256_file(p).unwrap_or_default() } else { String::new() };
                serde_json::json!([declared, h])
            })
            .collect()
    };

    // The key is inserted only when inputs are declared. Adding `"inputs_hash": null` to every
    // check would change the serialized string for checks that declare none, which would move
    // every digest in the repo and invalidate every recorded red→green. Absent means absent.
    let mut canonical = serde_json::Map::new();
    canonical.insert("kind".into(), serde_json::to_value(&check.kind).unwrap_or(serde_json::Value::Null));
    canonical.insert("target".into(), serde_json::to_value(&check.target).unwrap_or(serde_json::Value::Null));
    canonical.insert("expect".into(), serde_json::to_value(&expect).unwrap_or(serde_json::Value::Null));
    canonical.insert("script_hash".into(), script_hash);
    if !input_hashes.is_empty() {
        canonical.insert("inputs_hash".into(), serde_json::Value::Array(input_hashes));
    }
    let canonical = serde_json::Value::Object(canonical);
    let s = serde_json::to_string(&canonical).unwrap_or_default();
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    hex(&h.finalize())
}

/// Best-effort termination of a child **and its descendants**.
///
/// `Child::kill()` terminates only the direct child. A hung check is usually a runner — `pytest`,
/// `cargo`, `npm` — whose own children hold the work, so killing just the parent trades a hung
/// check for an orphaned process tree. There is no portable std API for this, so shell out to the
/// platform's tree-killer and fall back to the direct kill.
fn kill_tree(child: &mut std::process::Child) {
    let pid = child.id();
    if cfg!(windows) {
        let _ = Command::new("taskkill")
            .args(["/T", "/F", "/PID", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    } else {
        // Negative pid targets the process group when the child leads one; the direct kill below
        // covers the case where it does not.
        let _ = Command::new("kill")
            .args(["-KILL", &format!("-{pid}")])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    let _ = child.kill();
    // Reap, so the kill reaches quiescence instead of merely being requested. A teardown that
    // returns before the work stops is how orphans are made.
    let _ = child.wait();
}

fn sense_command(check: &Check) -> SenseResult {
    if check.target.is_empty() {
        return SenseResult { ok: false, signal: "command_exit".into(), evidence: "empty argv".into(), ..Default::default() };
    }
    let expect: i32 = check.expect.as_deref().unwrap_or("0").parse().unwrap_or(0);
    let started = Instant::now();
    let mut cmd = Command::new(&check.target[0]);
    cmd.args(&check.target[1..]);
    if let Some(dir) = &check.cwd {
        cmd.current_dir(dir);
    }

    // No deadline declared: keep the historical behaviour exactly.
    let Some(budget) = check.timeout_secs else {
        return match cmd.output() {
            Ok(out) => finish_command(check, expect, started, out.status.code(), &out.stdout, &out.stderr),
            Err(e) => SenseResult {
                ok: false,
                signal: "command_exit".into(),
                evidence: truncate(format!("spawn failed: {e}")),
                ..Default::default()
            },
        };
    };

    // argv-only, no shell. Piped stdio is drained on threads so a child that fills a pipe buffer
    // blocks on neither us nor itself while we are waiting out its deadline.
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            return SenseResult {
                ok: false,
                signal: "command_exit".into(),
                evidence: truncate(format!("spawn failed: {e}")),
                ..Default::default()
            }
        }
    };

    let mut out_pipe = child.stdout.take();
    let mut err_pipe = child.stderr.take();
    let out_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(p) = out_pipe.as_mut() {
            let _ = p.read_to_end(&mut buf);
        }
        buf
    });
    let err_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(p) = err_pipe.as_mut() {
            let _ = p.read_to_end(&mut buf);
        }
        buf
    });

    let deadline = Duration::from_secs(budget);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) => {
                if started.elapsed() >= deadline {
                    kill_tree(&mut child);
                    break None;
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(e) => {
                kill_tree(&mut child);
                return SenseResult {
                    ok: false,
                    signal: "command_exit".into(),
                    evidence: truncate(format!("wait failed: {e}")),
                    ..Default::default()
                };
            }
        }
    };

    let stdout = out_reader.join().unwrap_or_default();
    let stderr = err_reader.join().unwrap_or_default();

    let Some(status) = status else {
        // Timed out. A command killed at its deadline proved nothing, so it is never GREEN — and it
        // says "timed out" in words so the trace can tell a hang apart from an ordinary failure.
        let tail = String::from_utf8_lossy(if stderr.is_empty() { &stdout } else { &stderr });
        return SenseResult {
            ok: false,
            signal: "command_exit".into(),
            evidence: truncate(format!(
                "argv={:?} timed out after {}s (killed at {}ms) expect={}\n{}",
                check.target,
                budget,
                started.elapsed().as_millis(),
                expect,
                tail
            )),
            timed_out: true,
            exit_code: None,
        };
    };

    finish_command(check, expect, started, status.code(), &stdout, &stderr)
}

/// Shared verdict for a command that ran to completion, with or without a declared deadline.
fn finish_command(
    check: &Check,
    expect: i32,
    started: Instant,
    code: Option<i32>,
    stdout: &[u8],
    stderr: &[u8],
) -> SenseResult {
    // `code` is `None` when a signal killed the child (OOM killer, CI timeout, SIGKILL). The old
    // `unwrap_or(-1)` mapped that onto a real exit code, so "killed" and "exited -1" were
    // indistinguishable. A signalled process never exited with what we expected, so it is not ok.
    let ok = code == Some(expect);
    let tail = String::from_utf8_lossy(if stderr.is_empty() { stdout } else { stderr });
    let shown = match code {
        Some(c) => c.to_string(),
        None => "killed by signal".to_string(),
    };
    SenseResult {
        ok,
        signal: "command_exit".into(),
        evidence: truncate(format!(
            "argv={:?} exit={} expect={} ({}ms)\n{}",
            check.target,
            shown,
            expect,
            started.elapsed().as_millis(),
            tail
        )),
        timed_out: false,
        exit_code: code,
    }
}

fn sense_sha256(check: &Check) -> SenseResult {
    if check.target.is_empty() {
        return SenseResult {
            ok: false,
            signal: "file_sha256".into(),
            evidence: "empty target (need a file path)".into(),
            ..Default::default()
        };
    }
    let path = Path::new(&check.target[0]);
    match sha256_file(path) {
        Ok(got) => {
            let want = check.expect.clone().unwrap_or_default();
            SenseResult {
                ok: got == want,
                signal: "file_sha256".into(),
                evidence: format!("path={} got={} want={}", path.display(), got, want),
                ..Default::default()
            }
        }
        Err(e) => SenseResult {
            ok: false,
            signal: "file_sha256".into(),
            evidence: format!("read {} failed: {e}", path.display()),
            ..Default::default()
        },
    }
}

fn sense_regex(check: &Check) -> SenseResult {
    if check.target.is_empty() {
        return SenseResult {
            ok: false,
            signal: "regex_in_file".into(),
            evidence: "empty target (need a file path)".into(),
            ..Default::default()
        };
    }
    let path = Path::new(&check.target[0]);
    let pat = check.expect.clone().unwrap_or_default();
    let re = match regex::Regex::new(&pat) {
        Ok(r) => r,
        Err(e) => return SenseResult { ok: false, signal: "regex_in_file".into(), evidence: format!("bad regex: {e}"), ..Default::default() },
    };
    match std::fs::read_to_string(path) {
        Ok(contents) => SenseResult {
            ok: re.is_match(&contents),
            signal: "regex_in_file".into(),
            evidence: format!("path={} pattern={}", path.display(), pat),
            ..Default::default()
        },
        Err(e) => SenseResult { ok: false, signal: "regex_in_file".into(), evidence: format!("read failed: {e}"), ..Default::default() },
    }
}

fn sense_prompt_manifest(check: &Check) -> SenseResult {
    if check.target.is_empty() {
        return SenseResult {
            ok: false,
            signal: "prompt_manifest".into(),
            evidence: "empty target (need baseline manifest path)".into(),
            ..Default::default()
        };
    }
    let p = Path::new(&check.target[0]);
    match crate::prompt_ledger::verify_manifest_file(p) {
        Ok((m, v)) => SenseResult {
            ok: v.ok,
            signal: "prompt_manifest".into(),
            evidence: truncate(format!(
                "manifest={} composite={} added={:?} removed={:?} changed={:?}",
                p.display(), m.composite_sha256, v.added, v.removed, v.changed
            )),
            ..Default::default()
        },
        Err(e) => SenseResult {
            ok: false,
            signal: "prompt_manifest".into(),
            evidence: truncate(format!("read manifest {} failed: {e}", p.display())),
            ..Default::default()
        },
    }
}

fn sense_ui_behavior(check: &Check) -> SenseResult {
    if check.target.is_empty() {
        return SenseResult { ok: false, signal: "ui_behavior".into(), evidence: "empty target (need script path)".into(), ..Default::default() };
    }
    let started = Instant::now();
    let mut cmd = Command::new("node");
    cmd.arg(&check.target[0]);
    cmd.args(&check.target[1..]);
    cmd.arg("--json");
    if let Some(dir) = &check.cwd { cmd.current_dir(dir); }
    match cmd.output() {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let ok = serde_json::from_str::<serde_json::Value>(stdout.trim())
                .ok().and_then(|v| v.get("ok").and_then(|b| b.as_bool())).unwrap_or(false);
            let evidence = truncate(format!("script={} ok={} exit={} ({}ms)\n{}",
                &check.target[0], ok, out.status.code().unwrap_or(-1),
                started.elapsed().as_millis(), stdout.chars().take(512).collect::<String>()));
            SenseResult { ok, signal: "ui_behavior".into(), evidence, ..Default::default() }
        }
        Err(e) => SenseResult { ok: false, signal: "ui_behavior".into(),
            evidence: truncate(format!("node spawn failed: {e}")), ..Default::default() },
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

#[cfg(test)]
mod evidence_truncation {
    use super::*;

    /// `String::truncate` panics unless the index is a UTF-8 char boundary. Subprocess output is
    /// arbitrary bytes: pytest and rich draw box characters, cargo emits arrows, test names and
    /// paths carry non-ASCII. Whether byte MAX_EVIDENCE lands mid-character is data-dependent, so
    /// this is an intermittent crash in the arbiter, and it fires exactly when a check is already
    /// failing.
    #[test]
    fn truncate_does_not_panic_on_multibyte_boundary() {
        // '€' is 3 bytes. MAX_EVIDENCE % 3 == 2, so byte MAX_EVIDENCE falls strictly inside a char.
        let s = "\u{20AC}".repeat(MAX_EVIDENCE);
        let out = truncate(s);
        assert!(out.len() >= MAX_EVIDENCE, "expected a truncated-but-populated string");
    }

    /// Every multi-byte width must be safe, not just the one that happens to be tested.
    #[test]
    fn truncate_is_safe_for_every_multibyte_width() {
        for filler in ["\u{00E9}", "\u{20AC}", "\u{1F600}", "\u{2500}"] {
            let s = filler.repeat(MAX_EVIDENCE);
            let out = truncate(s);
            assert!(std::str::from_utf8(out.as_bytes()).is_ok(), "evidence must stay valid UTF-8");
        }
    }

    /// Test runners put the useful part — the failure summary and assertion diff — at the END.
    /// Keeping the head preserves banner noise and discards the diagnosis.
    #[test]
    fn truncate_keeps_the_diagnostic_tail() {
        let mut s = "banner noise\n".repeat(400);
        s.push_str("assert 1 == 2\nFAILED test_thing");
        let out = truncate(s);
        assert!(out.contains("FAILED test_thing"), "the tail explains the failure and must survive");
    }

    #[test]
    fn truncate_leaves_short_input_untouched() {
        let s = "short output".to_string();
        assert_eq!(truncate(s.clone()), s);
    }
}
