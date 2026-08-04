//! Issue #146: canonical_digest must fold the sha256 of EVERY target element that is an
//! existing file, not just target[0]. The dominant check shape in this repo puts the
//! interpreter at target[0] and the test or script file later in argv, for example
//! ["python","-m","pytest","tests/test_x.py","-q"], so binding only target[0] left the
//! test body outside the check identity. These four assertions pin the fixed behaviour.

use phoenix::sense::{canonical_digest, Check, CheckKind};
use std::fs;
use tempfile::tempdir;

/// Build a command_exit check from an argv, with a fixed expected exit code so the digest
/// is driven only by kind + target + the folded file hashes.
fn command_exit(target: Vec<String>) -> Check {
    Check {
        kind: CheckKind::CommandExit,
        target,
        expect: Some("0".to_string()),
        cwd: None,
        timeout_secs: None,
    }
}

fn path_str(p: &std::path::Path) -> String {
    p.to_string_lossy().into_owned()
}

/// Assertion 1: the digest changes when a file named ANYWHERE in target[1..] changes
/// content. This is the core issue #146 fix. Before it, a file at a non-zero argv position
/// was invisible to the check identity, so a strict test could be gutted without moving the
/// digest, and accept would chain the old REDs to the new GREEN.
#[test]
fn digest_changes_when_a_file_in_target_tail_changes() {
    let dir = tempdir().unwrap();
    let test_file = dir.path().join("test_x.py");
    fs::write(&test_file, b"def test_x():\n    assert 1 == 1\n").unwrap();

    // Interpreter at target[0], the test file at target[3]: a non-zero position.
    let check = command_exit(vec![
        "python".to_string(),
        "-m".to_string(),
        "pytest".to_string(),
        path_str(&test_file),
        "-q".to_string(),
    ]);
    let before = canonical_digest(&check);

    // Gut the assertion. Same argv, same path string, only the file bytes change.
    fs::write(&test_file, b"def test_x():\n    assert 1 == 2  # gutted\n").unwrap();
    let after = canonical_digest(&check);

    assert_ne!(
        before, after,
        "editing a file named at target[3] must change the digest (issue #146)"
    );
}

/// Assertion 2: the digest still changes when target[0] is a file, so the original issue #14
/// behaviour (a direct gate script like ["verify.py"]) does not regress.
#[test]
fn digest_still_changes_when_target0_is_a_file() {
    let dir = tempdir().unwrap();
    let script = dir.path().join("gate.py");
    fs::write(&script, b"raise SystemExit(0)  # v1\n").unwrap();

    let check = command_exit(vec![path_str(&script)]);
    let before = canonical_digest(&check);

    fs::write(&script, b"raise SystemExit(0)  # v2, different bytes\n").unwrap();
    let after = canonical_digest(&check);

    assert_ne!(
        before, after,
        "editing the gate script at target[0] must change the digest (issue #14 must not regress)"
    );
}

/// Assertion 3: a non-file argument (a flag like "-q") folds nothing.
///
/// The raw argv is always part of the digest, so renaming or dropping a flag would move the
/// digest through the `target` field alone and would prove nothing about the file-folding.
/// Instead we hold `target` byte-identical and toggle one absolute-path token from
/// "not a file" to "a real file". Only the token that becomes a real file moves the digest;
/// the "-q" flag, which is never a file, contributes nothing across the toggle. We also
/// confirm "-q" genuinely takes the non-file branch in this process.
#[test]
fn non_file_argument_contributes_nothing() {
    let dir = tempdir().unwrap();
    let toggle = dir.path().join("maybe.py"); // absolute path; no file on disk yet
    let target = vec!["python".to_string(), path_str(&toggle), "-q".to_string()];
    let check = command_exit(target);

    // Nothing in target is a file yet: maybe.py is absent, and "python" and "-q" are not files.
    let with_no_files = canonical_digest(&check);

    // Same argv. The only change on disk is that the toggle path becomes a real file.
    fs::write(&toggle, b"print('now real')\n").unwrap();
    let with_one_file = canonical_digest(&check);

    assert_ne!(
        with_no_files, with_one_file,
        "a target element that becomes a real file must fold into the digest"
    );
    assert!(
        !std::path::Path::new("-q").is_file(),
        "the flag -q must be a non-file so it never folds content"
    );
}

/// Assertion 4: the digest is stable across repeated calls with identical inputs.
#[test]
fn digest_is_stable_across_repeated_calls() {
    let dir = tempdir().unwrap();
    let test_file = dir.path().join("stable.py");
    fs::write(&test_file, b"def test_ok():\n    assert True\n").unwrap();

    let check = command_exit(vec![
        "python".to_string(),
        "-m".to_string(),
        "pytest".to_string(),
        path_str(&test_file),
    ]);

    let a = canonical_digest(&check);
    let b = canonical_digest(&check);
    let c = canonical_digest(&check);

    assert_eq!(a, b, "identical inputs must digest identically");
    assert_eq!(b, c, "identical inputs must digest identically");
}