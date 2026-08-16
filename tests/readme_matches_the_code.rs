//! The README must not describe a limit the code no longer has.
//!
//! This exists because the README claimed, for several releases after it stopped being true, that
//! *"command timeouts are represented in checks but are not yet enforced in-process."* They have
//! been enforced since #205 — `sense_command` spawns piped, polls against the deadline, kills the
//! whole process tree and waits for it to die.
//!
//! A stale limit is a worse defect than a missing one. It sits inside the section a careful reader
//! trusts most, so it spends the credibility the honest entries earned. And nothing catches it:
//! tests check the code, review checks the diff, and a sentence that was true when it was written
//! is invisible to both.
//!
//! So this pins the pair. The README says timeouts are enforced, and `sense.rs` must still contain
//! the mechanism that enforces them. Either half changing without the other fails here.

use std::path::{Path, PathBuf};

fn repo_file(relative: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(relative)
}

fn read(relative: &str) -> String {
    let path = repo_file(relative);
    std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()))
}

#[test]
fn the_readme_does_not_claim_timeouts_are_unenforced() {
    let readme = read("README.md");

    // The exact shape of the stale sentence, plus the looser forms an edit might reintroduce.
    for stale in [
        "are not yet enforced",
        "not yet enforced in-process",
        "timeouts are represented in checks but",
    ] {
        assert!(
            !readme.contains(stale),
            "README still says timeouts are unenforced (\"{stale}\"), but sense enforces them \
             since #205. A limit that stopped being true is worse than one that was never listed."
        );
    }
}

#[test]
fn the_readme_says_timeouts_are_enforced_and_sense_still_enforces_them() {
    let readme = read("README.md");
    assert!(
        readme.contains("Command timeouts are enforced"),
        "the honest-limits section must state the current behaviour, not omit it"
    );

    // The claim is only honest while the mechanism is there. If someone removes the enforcement,
    // this fails on the code side rather than leaving the README quietly lying again.
    let sense = read("src/sense.rs");
    for mechanism in ["fn kill_tree", "try_wait", "timed_out"] {
        assert!(
            sense.contains(mechanism),
            "README claims timeouts are enforced but sense.rs no longer contains `{mechanism}`"
        );
    }
}

#[test]
fn the_self_check_section_matches_the_audit_that_backs_it() {
    let readme = read("README.md");

    assert!(
        readme.contains("cargo test --test module_invariants"),
        "the self-check section must name the command a reader can run to verify it"
    );
    assert!(
        repo_file("tests/module_invariants.rs").exists(),
        "the README points at an audit that does not exist"
    );
}
