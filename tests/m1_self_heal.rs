//! M1 behavioral demo — the v0 pass criterion (per design critique: NOT tautological).
//!
//! Proves "bounded objective recovery": an INDEPENDENT signal (a command's exit code) goes
//! green -> (inject behavioral fault) -> red -> heal(rollback to blessed snapshot) -> green,
//! with the whole chain recorded in a tamper-evident trace.

use phoenix::sense::{sense, Check, CheckKind};
use phoenix::snapshot::snapshot;
use phoenix::{heal, HealCtx, Strategy, Trace};
use std::path::Path;

/// A portable "test command": the OS shell checks a sentinel file's content.
/// On Windows we use `cmd /C findstr`, elsewhere `grep`. This is the EXTERNAL invariant —
/// the heal is validated against a process exit code, not against the snapshot bytes.
fn check_contains(file: &Path, needle: &str) -> Check {
    let argv = if cfg!(windows) {
        vec![
            "cmd".into(),
            "/C".into(),
            "findstr".into(),
            "/C:".to_string() + needle,
            file.display().to_string(),
        ]
    } else {
        vec!["grep".into(), "-q".into(), needle.into(), file.display().to_string()]
    };
    Check { kind: CheckKind::CommandExit, target: argv, expect: Some("0".into()), cwd: None, timeout_secs: Some(30) }
}

#[test]
fn green_red_heal_green_with_trace() {
    let ws = tempfile::tempdir().unwrap();
    let root = ws.path();
    let src = root.join("logic.txt");
    let trace = Trace::default_in(root);

    // 1) GREEN baseline: file satisfies the behavioral invariant (contains GOOD_MARKER).
    std::fs::write(&src, "answer=GOOD_MARKER\n").unwrap();
    let good_check = check_contains(&src, "GOOD_MARKER");
    let baseline = sense(&good_check);
    trace.append("sense", "baseline", baseline.ok, &baseline.signal, &baseline.evidence).unwrap();
    assert!(baseline.ok, "baseline must be green: {}", baseline.evidence);

    // 2) Snapshot is BLESSED only because the check passes.
    let snap = snapshot(root, &src, &good_check).unwrap();
    assert!(snap.blessed, "snapshot must be blessed when green");
    let snap_id = snap.snap_id.clone().unwrap();
    trace.append("snapshot", &snap_id, snap.blessed, "snapshot", "blessed last-good").unwrap();

    // 3) Inject a BEHAVIORAL fault: file still exists, different bytes, invariant now violated.
    std::fs::write(&src, "answer=BROKEN\n").unwrap();
    let red = sense(&good_check);
    trace.append("sense", "post-fault", red.ok, &red.signal, &red.evidence).unwrap();
    assert!(!red.ok, "fault must be detected via the external command signal");

    // 4) HEAL by bounded rollback to the blessed snapshot; recovery validated by the SAME external check.
    let ctx = HealCtx {
        command: None,
        max_attempts: None,
        path: Some(src.display().to_string()),
        snap_id: Some(snap_id.clone()),
        recheck: good_check.clone(),
    };
    let h = heal(root, Strategy::Rollback, &ctx);
    trace.append("heal", &snap_id, h.healed, "rollback", &h.evidence).unwrap();
    assert!(h.healed, "heal must restore passing behavior: {}", h.evidence);
    assert_eq!(h.attempts, 1);

    // 5) GREEN again, independently confirmed.
    let recovered = sense(&good_check);
    assert!(recovered.ok, "must be green after heal");

    // Trace is intact and tamper-evident: 4 appends (sense, snapshot, sense, heal).
    let v = trace.verify();
    assert!(v.ok, "trace chain must verify; broken_at={:?}", v.broken_at);
    assert_eq!(v.rows, 4, "expected 4 trace rows");
}

#[test]
fn trace_is_tamper_evident() {
    let ws = tempfile::tempdir().unwrap();
    let t = Trace::default_in(ws.path());
    t.append("sense", "a", true, "command_exit", "ok").unwrap();
    t.append("heal", "b", true, "rollback", "healed").unwrap();
    assert!(t.verify().ok);

    // Tamper: rewrite a field in row 0 without fixing the hash chain.
    let p = ws.path().join(".phoenix").join("trace.jsonl");
    let content = std::fs::read_to_string(&p).unwrap();
    let tampered = content.replacen("\"ok\":true", "\"ok\":false", 1);
    std::fs::write(&p, tampered).unwrap();

    let v = t.verify();
    assert!(!v.ok, "tampering must be detected");
    assert_eq!(v.broken_at, Some(0));
}

#[test]
fn snapshot_refuses_to_bless_bad_state() {
    let ws = tempfile::tempdir().unwrap();
    let f = ws.path().join("x.txt");
    std::fs::write(&f, "answer=BROKEN\n").unwrap();
    // Check requires GOOD_MARKER, which is absent -> must NOT bless.
    let check = check_contains(&f, "GOOD_MARKER");
    let snap = snapshot(ws.path(), &f, &check).unwrap();
    assert!(!snap.blessed, "must not snapshot a known-bad state as good");
    assert!(snap.snap_id.is_none());
}
