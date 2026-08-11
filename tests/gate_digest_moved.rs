//! #173 -- a RED recorded under a different canonical digest is not a vacuous check.
//!
//! phoenix-proof senses the acceptance check on the base commit and again on the head. Since #158
//! folds every target file into the canonical digest, a check naming a file the pull request adds
//! digests differently on each side, so the base RED never matches the head digest and `accept`
//! reports `saw_red=false`. The verdict is correct. The message was not: it told the author to
//! reproduce a failure they had already reproduced. These two tests pin the difference.
//!
//! This file is its own integration-test target on purpose. It does not exist on the base commit,
//! so `cargo test --test gate_digest_moved` exits 101 there and the acceptance check fails closed,
//! which is what the base-RED half of phoenix-proof requires.

use phoenix::sense::{canonical_digest, Check};
use phoenix::{verify_gate, Trace};
use std::path::PathBuf;

fn tmp_ws(name: &str) -> PathBuf {
    let mut d = std::env::temp_dir();
    d.push(format!("phoenix_digest_{}_{}", name, std::process::id()));
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
fn reports_digest_moved_when_red_exists_under_another_digest() {
    let ws = tmp_ws("moved");
    let out = ws.join("out.txt");
    let check = regex_check(&out, "DONE");
    let digest = canonical_digest(&check);
    let tr = Trace::default_in(&ws);

    // The RED landed while the check still had its old digest, which is what happens when a file
    // named in `target` is added or edited between the two senses.
    let stale_digest = "0".repeat(64);
    std::fs::write(&out, "working...").unwrap();
    tr.append("sense", &stale_digest, false, "regex_in_file", "red").unwrap();
    std::fs::write(&out, "DONE").unwrap();
    tr.append("sense", &digest, true, "regex_in_file", "green").unwrap();

    let g = verify_gate(&ws, &check);
    assert!(!g.ok, "a RED under another digest still proves nothing about this check");
    assert!(!g.saw_red, "saw_red must stay false: that RED was not for this digest");
    assert!(g.currently_green, "the check passes right now");
    assert!(
        g.reason.contains("digest"),
        "the reason must name the digest mismatch, got: {}",
        g.reason
    );
    assert!(
        !g.reason.contains("never seen failing"),
        "the vacuous-check message describes the wrong problem here, got: {}",
        g.reason
    );
    let _ = std::fs::remove_dir_all(&ws);
}

#[test]
fn keeps_the_vacuous_message_when_the_trace_holds_no_red_at_all() {
    let ws = tmp_ws("vacuous");
    let out = ws.join("out.txt");
    let check = regex_check(&out, "DONE");
    let digest = canonical_digest(&check);
    let tr = Trace::default_in(&ws);

    // Nothing ever failed here, under this digest or any other. This is the case the original
    // message was written for and it has to keep saying so.
    std::fs::write(&out, "DONE").unwrap();
    tr.append("sense", &digest, true, "regex_in_file", "green").unwrap();

    let g = verify_gate(&ws, &check);
    assert!(!g.ok);
    assert!(!g.saw_red);
    assert!(
        g.reason.contains("never seen failing"),
        "a trace with no RED at all is the vacuous case, got: {}",
        g.reason
    );
    let _ = std::fs::remove_dir_all(&ws);
}
