//! Unit tests for the build-freshness DECISION (pure logic). The IO wrapper `build_freshness()`
//! depends on git + the compile-time build stamp, so the deterministic contract lives in
//! `decide_freshness`, tested here. This closes the gap where a stale binary reported GREEN against
//! its own stale embedded reference: the doctor now also compares the binary's build commit against
//! the source repo's current HEAD.

use phoenix::doctor::{decide_freshness, Freshness};

#[test]
fn up_to_date_when_commits_match() {
    assert_eq!(decide_freshness("abc123def456", Some("abc123def456")), Freshness::UpToDate);
}

#[test]
fn behind_when_source_is_newer() {
    assert_eq!(decide_freshness("abc123def456", Some("999fee000111")), Freshness::Behind);
}

#[test]
fn unknown_without_a_build_stamp() {
    // No stamp (built outside a git checkout) -> can't claim behind/ahead.
    assert_eq!(decide_freshness("unknown", Some("999fee000111")), Freshness::Unknown);
    assert_eq!(decide_freshness("", Some("999fee000111")), Freshness::Unknown);
}

#[test]
fn unknown_when_source_head_unavailable() {
    // Binary stamped, but the source repo isn't reachable (e.g. copied elsewhere) -> unknown.
    assert_eq!(decide_freshness("abc123def456", None), Freshness::Unknown);
}
