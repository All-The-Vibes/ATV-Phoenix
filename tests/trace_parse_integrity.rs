//! Regression tests for trace parse integrity (#111).
//!
//! `Trace::verify()` used to drop unparseable lines before checking the chain. That made a whole
//! class of corruption invisible: destroy a row's *structure* rather than a field's *value*, and the
//! row vanished from consideration — leaving a shorter chain that verified clean. The circuit-breaker
//! AGENTS.md requires never fired for it.
//!
//! These tests pin the fixed contract: an unparseable line is itself a break.

use phoenix::trace::Trace;
use tempfile::TempDir;

fn trace_at(dir: &TempDir) -> (Trace, std::path::PathBuf) {
    let p = dir.path().join("trace.jsonl");
    (Trace::at(p.clone()), p)
}

#[test]
fn destroying_the_only_row_is_detected() {
    let d = TempDir::new().unwrap();
    let (t, p) = trace_at(&d);
    t.append("sense", "d0", true, "command_exit", "only-row").unwrap();
    assert!(t.verify().ok, "baseline: a single honest row verifies");

    // Rename a field so the row no longer deserialises as TraceEvent.
    let c = std::fs::read_to_string(&p).unwrap();
    std::fs::write(&p, c.replacen("\"ok\"", "\"XX\"", 1)).unwrap();

    let v = t.verify();
    assert!(!v.ok, "a destroyed row must not verify as an intact empty chain (#111)");
    assert_eq!(v.broken_at, Some(0), "the break is reported at the damaged line");
    assert_eq!(v.rows, 1, "the damaged line is still counted; the file is not shorter");
}

#[test]
fn a_destroyed_middle_row_is_reported_at_its_own_index() {
    let d = TempDir::new().unwrap();
    let (t, p) = trace_at(&d);
    for i in 0..4 {
        t.append("sense", &format!("d{i}"), true, "command_exit", &format!("row-{i}")).unwrap();
    }

    let mut lines: Vec<String> =
        std::fs::read_to_string(&p).unwrap().lines().map(String::from).collect();
    lines[2] = "{ not json at all".to_string();
    std::fs::write(&p, lines.join("\n") + "\n").unwrap();

    let v = t.verify();
    assert!(!v.ok);
    assert_eq!(
        v.broken_at,
        Some(2),
        "previously a dropped row made row 3's prev_hash dangle, reporting the break at the wrong index"
    );
    assert_eq!(v.rows, 4, "all four lines are accounted for");
}

#[test]
fn a_truncated_final_line_is_detected() {
    let d = TempDir::new().unwrap();
    let (t, p) = trace_at(&d);
    t.append("sense", "d0", true, "command_exit", "first").unwrap();
    t.append("sense", "d1", true, "command_exit", "second").unwrap();

    // Simulate a writer killed mid-append.
    let mut c = std::fs::read_to_string(&p).unwrap();
    c.push_str("{\"ts\":\"1\",\"tool\":\"sen");
    std::fs::write(&p, c).unwrap();

    let v = t.verify();
    assert!(!v.ok, "a torn tail must be visible, not silently discarded");
    assert_eq!(v.broken_at, Some(2));
}

#[test]
fn a_value_level_tamper_is_still_detected() {
    let d = TempDir::new().unwrap();
    let (t, p) = trace_at(&d);
    t.append("sense", "d0", true, "command_exit", "original").unwrap();
    t.append("sense", "d1", true, "command_exit", "second").unwrap();

    let c = std::fs::read_to_string(&p).unwrap();
    std::fs::write(&p, c.replacen("original", "TAMPERED", 1)).unwrap();

    let v = t.verify();
    assert!(!v.ok, "the pre-existing hash-mismatch path must keep working");
    assert_eq!(v.broken_at, Some(0));
}

#[test]
fn an_intact_chain_still_verifies_and_counts_correctly() {
    let d = TempDir::new().unwrap();
    let (t, _) = trace_at(&d);
    for i in 0..5 {
        t.append("sense", &format!("d{i}"), true, "command_exit", "ok").unwrap();
    }

    let v = t.verify();
    assert!(v.ok, "the fix must not make honest chains fail");
    assert_eq!(v.rows, 5);
    assert_eq!(v.broken_at, None);
    assert_ne!(v.head_hash, "GENESIS", "head advances past genesis");
}

#[test]
fn an_absent_trace_is_empty_not_broken() {
    let d = TempDir::new().unwrap();
    let t = Trace::at(d.path().join("never-written.jsonl"));

    let v = t.verify();
    assert!(v.ok, "nothing written is not corruption");
    assert_eq!(v.rows, 0);
    assert_eq!(v.head_hash, "GENESIS");
}

#[test]
fn blank_lines_do_not_count_as_corruption() {
    let d = TempDir::new().unwrap();
    let (t, p) = trace_at(&d);
    t.append("sense", "d0", true, "command_exit", "row").unwrap();

    let c = std::fs::read_to_string(&p).unwrap();
    std::fs::write(&p, format!("{c}\n\n")).unwrap();

    let v = t.verify();
    assert!(v.ok, "trailing blank lines are formatting, not tampering");
    assert_eq!(v.rows, 1);
}

#[test]
fn read_all_still_returns_only_parseable_events() {
    let d = TempDir::new().unwrap();
    let (t, p) = trace_at(&d);
    t.append("sense", "d0", true, "command_exit", "good").unwrap();
    let c = std::fs::read_to_string(&p).unwrap();
    std::fs::write(&p, c + "{ garbage\n").unwrap();

    assert_eq!(t.read_all().len(), 1, "read_all keeps its lenient contract for event consumers");
    assert!(!t.verify().ok, "but verify no longer shares that leniency");
}
