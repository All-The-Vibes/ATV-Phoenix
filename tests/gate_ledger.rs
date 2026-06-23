//! Gate-ledger tests — the failure-first acceptance proof that makes phoenix-ralph / phoenix-goal
//! trustworthy. Completion is DERIVED from the trace, not authored. These prove:
//!   1. a check that went RED then GREEN (failure-first) and is green now → ACCEPTED
//!   2. a check that is green now but was NEVER red in the trace (vacuous) → REJECTED
//!   3. a check whose trace was tampered → REJECTED

use phoenix::sense::{canonical_digest, Check};
use phoenix::{verify_gate, Trace};
use std::path::PathBuf;

fn tmp_ws(name: &str) -> PathBuf {
    let mut d = std::env::temp_dir();
    d.push(format!("phoenix_gate_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(d.join(".phoenix")).unwrap();
    d
}

fn regex_check(file: &PathBuf, pat: &str) -> Check {
    serde_json::from_str(&format!(
        r#"{{"kind":"regex_in_file","target":["{}"],"expect":"{}"}}"#,
        file.display().to_string().replace('\\', "\\\\"),
        pat
    ))
    .unwrap()
}

#[test]
fn accepts_failure_first_red_then_green() {
    let ws = tmp_ws("good");
    let out = ws.join("out.txt");
    let check = regex_check(&out, "DONE");
    let digest = canonical_digest(&check);
    let tr = Trace::default_in(&ws);

    // Simulate the loop: reproduce-first (RED), then build, then GREEN — same canonical check.
    std::fs::write(&out, "working...").unwrap();
    tr.append("sense", &digest, false, "regex_in_file", "red").unwrap();
    std::fs::write(&out, "DONE").unwrap(); // the "fix"
    tr.append("sense", &digest, true, "regex_in_file", "green").unwrap();

    let g = verify_gate(&ws, &check);
    assert!(g.ok, "should accept red→green that is currently green: {}", g.reason);
    assert!(g.saw_red && g.green_after_red && g.currently_green && g.trace_intact);
    let _ = std::fs::remove_dir_all(&ws);
}

#[test]
fn rejects_vacuous_never_red_check() {
    let ws = tmp_ws("vacuous");
    let out = ws.join("out.txt");
    let check = regex_check(&out, "DONE");
    let digest = canonical_digest(&check);
    let tr = Trace::default_in(&ws);

    // The check is green NOW, and the trace has only a GREEN event — it was never seen failing.
    std::fs::write(&out, "DONE").unwrap();
    tr.append("sense", &digest, true, "regex_in_file", "green").unwrap();

    let g = verify_gate(&ws, &check);
    assert!(!g.ok, "a never-red check must NOT count as a gate");
    assert!(g.currently_green, "it is green now");
    assert!(!g.saw_red, "but it was never observed red");
    let _ = std::fs::remove_dir_all(&ws);
}

#[test]
fn rejects_tampered_trace() {
    let ws = tmp_ws("tamper");
    let out = ws.join("out.txt");
    let check = regex_check(&out, "DONE");
    let digest = canonical_digest(&check);
    let tr = Trace::default_in(&ws);

    std::fs::write(&out, "working...").unwrap();
    tr.append("sense", &digest, false, "regex_in_file", "red").unwrap();
    std::fs::write(&out, "DONE").unwrap();
    tr.append("sense", &digest, true, "regex_in_file", "green").unwrap();

    // Tamper: flip the recorded red event to green by editing the JSONL directly.
    let p = ws.join(".phoenix").join("trace.jsonl");
    let content = std::fs::read_to_string(&p).unwrap();
    let hacked = content.replacen("\"ok\":false", "\"ok\":true", 1);
    std::fs::write(&p, hacked).unwrap();

    let g = verify_gate(&ws, &check);
    assert!(!g.ok, "a tampered trace must break acceptance");
    assert!(!g.trace_intact, "tamper-evidence must catch the edit");
    let _ = std::fs::remove_dir_all(&ws);
}

#[test]
fn rejects_gate_script_edit() {
    // Issue #14: editing the gate script (the file target[0] points to) must invalidate
    // previously-recorded trace events, so accept correctly rejects the modified gate.
    // Before this fix, check_digest was derived from the spec only (argv/expect), so
    // v1 and v2 of a gate script produced IDENTICAL digests — a weakened gate could be
    // certified as ok=true, trace_intact=true.
    use phoenix::sense::{canonical_digest, Check};

    let ws = tmp_ws("script_edit");
    let script = ws.join("gate.py");

    // Write v1 of the gate script (will be the "original" gate)
    std::fs::write(&script, b"# gate v1: weak assertion\nprint('ok')\n").unwrap();

    // Build check pointing at the script
    let check_v1: Check = serde_json::from_str(&format!(
        r#"{{"kind":"command_exit","target":["{}"],"expect":0}}"#,
        script.display().to_string().replace('\\', "\\\\")
    )).unwrap();
    let digest_v1 = canonical_digest(&check_v1);

    // Simulate a completed run: red then green under v1
    let tr = phoenix::Trace::default_in(&ws);
    tr.append("sense", &digest_v1, false, "command_exit", "red").unwrap();
    tr.append("sense", &digest_v1, true,  "command_exit", "green").unwrap();

    // Now "edit" the gate script (v2: agent strengthens or weakens it)
    std::fs::write(&script, b"# gate v2: different assertions\nprint('ok')\n").unwrap();

    // Re-derive the digest for the same check spec — it MUST differ because the script changed
    let check_v2: Check = serde_json::from_str(&format!(
        r#"{{"kind":"command_exit","target":["{}"],"expect":0}}"#,
        script.display().to_string().replace('\\', "\\\\")
    )).unwrap();
    let digest_v2 = canonical_digest(&check_v2);

    assert_ne!(digest_v1, digest_v2,
        "digest must change when the gate script body changes (issue #14 regression guard)");

    // accept on the MODIFIED check must be rejected — the trace has no red->green for digest_v2
    let result = phoenix::verify_gate(&ws, &check_v2);
    assert!(!result.ok,
        "accept must reject the modified gate: old trace events used digest_v1, not digest_v2");
    assert!(!result.saw_red,
        "no RED was ever observed for digest_v2 (the edited script)");

    let _ = std::fs::remove_dir_all(&ws);
}