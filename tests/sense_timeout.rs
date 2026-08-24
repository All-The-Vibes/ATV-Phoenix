//! #203 — `Check.timeout_secs` is part of the public MCP tool schema. Until this test passed it was
//! never read: `sense_command` called `Command::output()`, which blocks until the child exits.
//!
//! The failure that motivated it: a check declaring a 2s bound against an 8s command returned
//! `ok=true` after 14,505ms. A caller that sets the bound believes the check is bounded; a check
//! that never returns stalls an autonomous loop **silently instead of going RED**.

use phoenix::sense::{sense, Check, CheckKind};
use std::time::Instant;

/// A command that outlives the declared budget. Portable across the runners we use.
fn slow_argv(seconds: u32) -> Vec<String> {
    if cfg!(windows) {
        vec![
            "powershell".into(),
            "-NoProfile".into(),
            "-Command".into(),
            format!("Start-Sleep -Seconds {seconds}; exit 0"),
        ]
    } else {
        vec!["sh".into(), "-c".into(), format!("sleep {seconds}; exit 0")]
    }
}

fn check(target: Vec<String>, timeout_secs: Option<u64>) -> Check {
    Check {
        kind: CheckKind::CommandExit,
        target,
        expect: Some("0".into()),
        cwd: None,
        timeout_secs,
        ..Default::default()
    }
}

/// The whole point: the declared bound must actually bound the call.
#[test]
fn declared_timeout_is_enforced() {
    let started = Instant::now();
    let r = sense(&check(slow_argv(8), Some(2)));
    let elapsed = started.elapsed();

    assert!(
        elapsed.as_secs() < 6,
        "timeout_secs=2 must bound the call; it took {}ms",
        elapsed.as_millis()
    );
    assert!(!r.ok, "a command killed at its deadline never proved anything and must not be GREEN");
}

/// Orthogonal outcomes reported independently: a timeout must be legible as a timeout, not as a
/// generic non-zero exit. Otherwise "hung" and "failed" are indistinguishable in the trace.
#[test]
fn timeout_is_distinguishable_from_an_ordinary_failure() {
    let r = sense(&check(slow_argv(8), Some(2)));
    assert!(r.timed_out, "the result must carry the timeout as its own fact");
    assert!(
        r.evidence.to_lowercase().contains("timed out"),
        "evidence must say so in words; got: {}",
        r.evidence
    );
}

/// A bound that is not exceeded must not change the verdict.
#[test]
fn fast_command_under_budget_is_unaffected() {
    let argv = if cfg!(windows) {
        vec!["powershell".into(), "-NoProfile".into(), "-Command".into(), "exit 0".to_string()]
    } else {
        vec!["sh".into(), "-c".into(), "exit 0".to_string()]
    };
    let r = sense(&check(argv, Some(30)));
    assert!(r.ok, "a passing command inside its budget stays GREEN: {}", r.evidence);
    assert!(!r.timed_out);
}

/// Absent `timeout_secs` keeps the historical behaviour, so existing checks are unaffected.
#[test]
fn absent_timeout_still_runs_to_completion() {
    let argv = if cfg!(windows) {
        vec!["powershell".into(), "-NoProfile".into(), "-Command".into(), "exit 3".to_string()]
    } else {
        vec!["sh".into(), "-c".into(), "exit 3".to_string()]
    };
    let r = sense(&check(argv, None));
    assert!(!r.ok);
    assert!(!r.timed_out);
    assert_eq!(r.exit_code, Some(3), "a real exit code must survive as itself");
}
