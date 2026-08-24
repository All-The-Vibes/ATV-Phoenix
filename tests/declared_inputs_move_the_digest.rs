//! #211 - a GREEN must go stale when something it depends on moves.
//!
//! `canonical_digest` folds the sha256 of every file named in `target`, so editing a test file the
//! check names moves the digest and any recorded RED stops binding. It cannot see what that file
//! imports: a helper module, a fixture, the module actually under test. Those move underneath a
//! recorded GREEN, and the GREEN keeps asserting a world that no longer exists.
//!
//! Under `phoenix-mission` that is not hypothetical. Goals declare `depends_on`, so a sibling goal
//! landing a commit is exactly this case, and the DAG already knows it happened.
//!
//! `Check.inputs` is where a check declares those files. This pins four properties: the fold works,
//! it is a set rather than a sequence, a check declaring none keeps its old identity byte for byte,
//! and `accept` actually refuses once a declared input moves.

use phoenix::sense::{canonical_digest, Check, CheckKind};
use phoenix::{verify_gate, Trace};
use std::path::PathBuf;

fn tmp_ws(name: &str) -> PathBuf {
    let mut d = std::env::temp_dir();
    d.push(format!("phoenix_inputs_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(d.join(".phoenix")).unwrap();
    d
}

fn regex_check(file: &PathBuf, pat: &str, inputs: Vec<String>) -> Check {
    Check {
        kind: CheckKind::RegexInFile,
        target: vec![file.display().to_string()],
        expect: Some(pat.to_string()),
        inputs,
        ..Default::default()
    }
}

#[test]
fn a_declared_input_moving_moves_the_digest() {
    let ws = tmp_ws("moves");
    let out = ws.join("out.txt");
    let helper = ws.join("helper.py");
    std::fs::write(&out, "DONE").unwrap();
    std::fs::write(&helper, "def helper():\n    return 1\n").unwrap();

    let declared = regex_check(&out, "DONE", vec![helper.display().to_string()]);
    let before = canonical_digest(&declared);

    // The helper changes. Nothing named in `target` changed, so the pre-#211 fold saw nothing.
    std::fs::write(&helper, "def helper():\n    return 2\n").unwrap();
    let after = canonical_digest(&declared);

    assert_ne!(
        before, after,
        "a declared input changed content and the digest did not move, so a recorded GREEN would \\
         still bind to a check whose meaning changed"
    );

    // Control: the same check without the declaration cannot see it, which is the old behaviour
    // and is why the declaration has to exist rather than being inferred.
    let undeclared = regex_check(&out, "DONE", Vec::new());
    let u_before = canonical_digest(&undeclared);
    std::fs::write(&helper, "def helper():\n    return 3\n").unwrap();
    assert_eq!(
        u_before,
        canonical_digest(&undeclared),
        "an undeclared file must not move the digest; the fold is opt-in by declaration"
    );
}

#[test]
fn inputs_are_a_set_not_a_sequence() {
    let ws = tmp_ws("set");
    let out = ws.join("out.txt");
    let a = ws.join("a.py");
    let b = ws.join("b.py");
    std::fs::write(&out, "DONE").unwrap();
    std::fs::write(&a, "a").unwrap();
    std::fs::write(&b, "b").unwrap();
    let (sa, sb) = (a.display().to_string(), b.display().to_string());

    let one = canonical_digest(&regex_check(&out, "DONE", vec![sa.clone(), sb.clone()]));
    let two = canonical_digest(&regex_check(&out, "DONE", vec![sb.clone(), sa.clone()]));
    assert_eq!(one, two, "reordering a declaration does not change what the check depends on");

    let dup = canonical_digest(&regex_check(&out, "DONE", vec![sa.clone(), sb, sa]));
    assert_eq!(one, dup, "declaring the same file twice does not change what it depends on");
}

#[test]
fn a_missing_declared_input_still_moves_the_digest() {
    let ws = tmp_ws("missing");
    let out = ws.join("out.txt");
    let gone = ws.join("gone.py");
    std::fs::write(&out, "DONE").unwrap();
    std::fs::write(&gone, "here").unwrap();

    let check = regex_check(&out, "DONE", vec![gone.display().to_string()]);
    let present = canonical_digest(&check);
    std::fs::remove_file(&gone).unwrap();

    assert_ne!(
        present,
        canonical_digest(&check),
        "deleting a file the check declares must move the digest, not read like it was never \\
         declared"
    );
}

#[test]
fn a_check_declaring_no_inputs_keeps_its_pre_211_identity() {
    // Captured from main at 935abed, before `inputs` existed. Every recorded red->green in the
    // repo and in every live trace is keyed on digests like these. If adding the field moved them,
    // adopting this change would silently invalidate the entire history, and `accept` would start
    // reporting saw_red=false everywhere.
    let argv_check = Check {
        kind: CheckKind::CommandExit,
        target: vec!["cargo".into(), "test".into(), "--locked".into()],
        expect: Some("0".into()),
        ..Default::default()
    };
    assert_eq!(
        canonical_digest(&argv_check),
        "4721fdc702d9cf0b42789c9eb52b51318ceee625dd5e6e9adb9f8efeb6a1fe35",
        "a command_exit check declaring no inputs must digest exactly as it did before #211"
    );

    let file_check = Check {
        kind: CheckKind::RegexInFile,
        target: vec!["README.md".into()],
        expect: Some("Phoenix".into()),
        ..Default::default()
    };
    assert_eq!(
        canonical_digest(&file_check),
        "58c8a223eb05cde1b16fb8fb24484fdc4819848ab09df40e792463fc08f90176",
        "a regex_in_file check declaring no inputs must digest exactly as it did before #211"
    );
}

#[test]
fn accept_refuses_once_a_declared_input_moves() {
    let ws = tmp_ws("accept");
    let out = ws.join("out.txt");
    let helper = ws.join("helper.py");
    std::fs::write(&helper, "def helper():\n    return 1\n").unwrap();
    let check = regex_check(&out, "DONE", vec![helper.display().to_string()]);
    let tr = Trace::default_in(&ws);

    // A clean red->green under the declaration as it stood.
    std::fs::write(&out, "working...").unwrap();
    let digest = canonical_digest(&check);
    tr.append("sense", &digest, false, "regex_in_file", "red").unwrap();
    std::fs::write(&out, "DONE").unwrap();
    tr.append("sense", &digest, true, "regex_in_file", "green").unwrap();

    let before = verify_gate(&ws, &check);
    assert!(before.ok, "the proof is sound while nothing has moved: {}", before.reason);

    // The helper the check declared now says something different. The check still passes, and that
    // is the trap: currently_green stays true while the proof no longer describes this world.
    std::fs::write(&helper, "def helper():\n    return 2\n").unwrap();

    let after = verify_gate(&ws, &check);
    assert!(after.currently_green, "the check itself still passes; only its identity moved");
    assert!(
        !after.ok,
        "accept still reported ok after a declared input moved, so a stale GREEN licensed the work"
    );
    assert!(
        !after.saw_red,
        "the recorded RED was for the old identity and must stop counting for the new one"
    );
}
