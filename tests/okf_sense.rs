//! OKF self-sensing test — the Phoenix spine senses the conformance of its OWN committed knowledge
//! bundle through the exact same `command_exit` mechanism a run uses, with no OKF-specific Rust code.
//!
//! This is the M4 "knowledge is a sensed artifact" claim, asserted in CI: if the committed
//! `examples/okf-code-graph/` bundle ever drifts out of OKF conformance, `cargo test` goes red —
//! the same discipline `skills_doctor.rs` applies to the bundled SKILL.md files.

use phoenix::sense::{sense, Check, CheckKind};
use std::path::PathBuf;
use std::process::Command;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// Find a Python interpreter; the OKF gates are portable Python. Returns None if none is callable,
/// so the test can skip gracefully on a host without Python rather than report a false failure.
fn python() -> Option<&'static str> {
    for cand in ["python", "python3"] {
        if Command::new(cand).arg("--version").output().map(|o| o.status.success()).unwrap_or(false) {
            return Some(cand);
        }
    }
    None
}

fn validate_check(py: &str, bundle: &str) -> Check {
    Check {
        kind: CheckKind::CommandExit,
        target: vec![
            py.to_string(),
            "skills/phoenix-okf/scripts/okf_validate.py".into(),
            bundle.into(),
        ],
        expect: Some("0".into()),
        cwd: Some(repo_root().display().to_string()),
        timeout_secs: Some(60),
    }
}

#[test]
fn spine_senses_committed_code_bundle_conformant() {
    let Some(py) = python() else {
        eprintln!("skipping: no python interpreter on PATH");
        return;
    };
    let r = sense(&validate_check(py, "examples/okf-code-graph"));
    assert!(r.ok, "committed OKF code bundle must sense GREEN through the spine:\n{}", r.evidence);
}

#[test]
fn spine_senses_external_bundle_conformant() {
    let Some(py) = python() else {
        eprintln!("skipping: no python interpreter on PATH");
        return;
    };
    let r = sense(&validate_check(py, "examples/okf-external-demo"));
    assert!(r.ok, "committed external OKF bundle must sense GREEN through the spine:\n{}", r.evidence);
}

#[test]
fn spine_senses_a_broken_bundle_red() {
    let Some(py) = python() else {
        eprintln!("skipping: no python interpreter on PATH");
        return;
    };
    // Build a deliberately non-conformant bundle in a temp dir: one concept with no `type`.
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    std::fs::write(root.join("index.md"), "---\nokf_version: 0.1\n---\n# tmp bundle\n").unwrap();
    std::fs::create_dir_all(root.join("concepts")).unwrap();
    std::fs::write(root.join("concepts").join("bad.md"), "# no frontmatter, no type\n").unwrap();

    let check = Check {
        kind: CheckKind::CommandExit,
        target: vec![
            py.to_string(),
            repo_root()
                .join("skills/phoenix-okf/scripts/okf_validate.py")
                .display()
                .to_string(),
            root.display().to_string(),
        ],
        expect: Some("0".into()),
        cwd: None,
        timeout_secs: Some(60),
    };
    let r = sense(&check);
    assert!(!r.ok, "a bundle whose concept lacks `type` must sense RED:\n{}", r.evidence);
}
