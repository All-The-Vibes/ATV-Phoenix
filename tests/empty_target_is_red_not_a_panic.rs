//! #211 groundwork - a check with no target must read RED, never crash the sensor.
//!
//! `sense_command`, `sense_prompt_manifest` and `sense_ui_behavior` each guard `target.is_empty()`
//! and return `ok: false`. `sense_sha256` and `sense_regex` did not: both indexed `target[0]`
//! straight away, so an empty argv panicked with an index-out-of-bounds instead of going RED.
//!
//! Why that matters more than a tidy-up. The whole harness rests on `sense` reporting failure as a
//! value a caller can act on. A sensor that panics takes the process with it, so an autonomous loop
//! loses the one thing it uses to tell success from failure, and it loses it at exactly the moment
//! something was already wrong.
//!
//! It is also the blocker under #211. That issue wants `inputs` added to `Check`, which needs the 19
//! struct-literal sites converted to `..Default::default()`, which needs `Check` to derive
//! `Default`. A derived default has an empty `target`, so deriving it while two kinds panic on an
//! empty target would hand every call site a foot-gun. This closes that hole first.

use phoenix::sense::{sense, Check, CheckKind};

fn empty(kind: CheckKind, expect: Option<&str>) -> Check {
    Check {
        kind,
        target: Vec::new(),
        expect: expect.map(|s| s.to_string()),
        cwd: None,
        timeout_secs: None,
    }
}

#[test]
fn every_kind_reads_red_when_the_target_is_empty() {
    let cases = [
        (CheckKind::CommandExit, Some("0")),
        (CheckKind::FileSha256, Some("00")),
        (CheckKind::RegexInFile, Some("anything")),
        (CheckKind::PromptManifest, None),
        (CheckKind::UiBehavior, None),
    ];

    for (kind, expect) in cases {
        let label = format!("{kind:?}");
        let r = sense(&empty(kind, expect));
        assert!(
            !r.ok,
            "{label} with an empty target reported ok=true; a check that names nothing cannot pass"
        );
        assert!(
            !r.evidence.is_empty(),
            "{label} went RED with no evidence; a caller cannot tell why"
        );
    }
}

#[test]
fn the_two_file_kinds_say_what_was_missing() {
    for kind in [CheckKind::FileSha256, CheckKind::RegexInFile] {
        let label = format!("{kind:?}");
        let r = sense(&empty(kind, Some("00")));
        assert!(!r.ok, "{label} must be RED on an empty target");
        assert!(
            r.evidence.to_lowercase().contains("empty"),
            "{label} evidence should name the empty target, got: {}",
            r.evidence
        );
    }
}
