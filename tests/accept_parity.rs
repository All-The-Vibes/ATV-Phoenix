//! #182 -- the Rust half of the failure-first parity contract.
//!
//! `tests/accept_parity_cases.json` is the single fixture. `tests/test_accept_parity.py` runs
//! every case through `phoenix_learn.accept.verify_gate`; this file runs the same cases through
//! `src/accept.rs::verify_gate`. A rule changed on one side and not the other fails one suite.
//!
//! The contract the fixture states: given an intact trace and a live check whose result equals
//! the last recorded observation, both gates agree on saw_red, green_after_red, currently_green
//! and ok. Python has no trace, so trace_intact is outside the contract; it is asserted here
//! separately because a broken chain would make every other field meaningless.
//!
//! Each case builds its own workspace with a `regex_in_file` check over a file that is written
//! once, before `canonical_digest` runs, and never touched again. #158 folds the contents of
//! every existing target file into the digest, so a file edited mid-case would move the digest
//! and the appended rows would stop binding the check, which is the bug #173 is about. Making
//! the check RED is done by asking for a pattern the file does not contain, not by editing it.

use phoenix::sense::{canonical_digest, Check};
use phoenix::{verify_gate, Trace};
use std::path::PathBuf;

#[derive(serde::Deserialize)]
struct Case {
    name: String,
    trials: Vec<bool>,
    saw_red: bool,
    green_after_red: bool,
    currently_green: bool,
    ok: bool,
}

#[derive(serde::Deserialize)]
struct Fixture {
    cases: Vec<Case>,
}

fn fixture() -> Fixture {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/accept_parity_cases.json");
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    serde_json::from_str(&raw).expect("accept_parity_cases.json is not the expected shape")
}

fn workspace(name: &str) -> PathBuf {
    let mut d = std::env::temp_dir();
    d.push(format!("phoenix_parity_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(d.join(".phoenix")).unwrap();
    d
}

fn check_over(file: &PathBuf, pattern: &str) -> Check {
    serde_json::from_str(&format!(
        r#"{{"kind":"regex_in_file","target":["{}"],"expect":"{}"}}"#,
        file.display().to_string().replace('\\', "\\\\"),
        pattern
    ))
    .unwrap()
}

#[test]
fn rust_gate_matches_the_shared_contract() {
    let cases = fixture().cases;
    assert!(!cases.is_empty(), "the fixture holds no cases, so this test proves nothing");

    for case in &cases {
        let ws = workspace(&case.name);
        let subject = ws.join("subject.txt");
        std::fs::write(&subject, "DONE").unwrap();

        // The live check has to end up agreeing with the last recorded trial, which is what the
        // fixture's currently_green column means. An empty case has no last trial and the
        // Python gate reports currently_green=false for it, so the check is RED there too.
        let want_live_green = *case.trials.last().unwrap_or(&false);
        let check = check_over(&subject, if want_live_green { "DONE" } else { "ABSENT" });

        let digest = canonical_digest(&check);
        let trace = Trace::default_in(&ws);
        for (i, ok) in case.trials.iter().enumerate() {
            trace
                .append("sense", &digest, *ok, "regex_in_file", &format!("trial {i}"))
                .unwrap();
        }

        let got = verify_gate(&ws, &check);

        assert!(got.trace_intact, "{}: the trace chain broke, so nothing below is meaningful", case.name);
        assert_eq!(got.saw_red, case.saw_red, "{}: saw_red", case.name);
        assert_eq!(got.green_after_red, case.green_after_red, "{}: green_after_red", case.name);
        assert_eq!(got.currently_green, case.currently_green, "{}: currently_green", case.name);
        assert_eq!(
            got.ok, case.ok,
            "{}: ok. The Rust gate disagrees with tests/accept_parity_cases.json, which \
             tests/test_accept_parity.py holds the Python gate to.",
            case.name
        );

        let _ = std::fs::remove_dir_all(&ws);
    }
}

#[test]
fn one_green_after_one_red_is_enough() {
    // The drift #182 recorded ran the other way: the deleted phoenix_loop.py copy demanded two
    // greens. Pinning the single-green case on its own keeps that requirement from creeping back
    // into either language, since every other case in the fixture has two greens or none.
    let ws = workspace("single_green");
    let subject = ws.join("subject.txt");
    std::fs::write(&subject, "DONE").unwrap();
    let check = check_over(&subject, "DONE");
    let digest = canonical_digest(&check);
    let trace = Trace::default_in(&ws);
    trace.append("sense", &digest, false, "regex_in_file", "red").unwrap();
    trace.append("sense", &digest, true, "regex_in_file", "green").unwrap();

    let got = verify_gate(&ws, &check);
    assert!(got.ok, "one red then one green satisfies failure-first, got: {}", got.reason);

    let _ = std::fs::remove_dir_all(&ws);
}
