//! Every module states its invariants, or records why it has none (#212).
//!
//! Phoenix's modules each enforce their own rules inline, and until this test nothing stated those
//! rules anywhere a new code path had to satisfy them, or an audit could check they still existed.
//! `snapshot` refuses to bless against a failing check, `accept` computes
//! `trace_intact && saw_red && green_after_red && currently_green`, `heal` bounds its own retries —
//! each of those is a real rule living as an expression inside one function.
//!
//! The proof that the gap is load-bearing is #203. `Check.timeout_secs` sat in the public MCP schema
//! and was read nowhere, so a check declaring a 2-second bound returned GREEN after 14,505 ms. The
//! invariant "a CommandExit result's measured elapsed time must not exceed its declared
//! `timeout_secs`" is obvious once written down. It was in nobody's head, so nothing noticed.
//!
//! ## The obligation
//!
//! Every file under `src/` either states at least one `//! INVARIANT: <property>` or carries a
//! `//! No runtime invariant: <reason>`. Both markers live in the module doc header the file already
//! has, so this adds an obligation rather than a subsystem — there is no registry to register with
//! and no bus to publish on.
//!
//! The escape hatch is deliberate and expected to be the majority answer. A rule demanding a real
//! invariant per module becomes ceremony within a month; this one demands a *decision*, recorded
//! in-tree and machine-audited. The cheap answer is always available — you just have to name the
//! reason, and the reason is reviewable in a diff.
//!
//! ## Why discovery, not a roster
//!
//! The audit walks `src/` rather than reading a list. A hardcoded roster audits the modules somebody
//! remembered to add to it, which is precisely the set least likely to contain the problem, and it
//! leaves module N+1 uncovered by construction. Discovery makes a new module covered by default:
//! adding one and forgetting to state its invariant fails this test.
//!
//! ## Scope: nothing under src/ is skipped
//!
//! `lib.rs` and `src/bin/*.rs` are audited like any other file. Skipping them would need its own
//! justification, and "this file is a composition root" is exactly the kind of claim that should be
//! written down and reviewed rather than encoded as a silent exception here. A file with genuinely
//! nothing to assert says so in one line.

use std::path::{Path, PathBuf};

/// What a file said about its invariants.
#[derive(Debug, PartialEq, Eq)]
enum Verdict {
    /// One or more non-empty `INVARIANT:` statements.
    States(usize),
    /// A non-empty `No runtime invariant:` reason.
    Justified,
    /// Neither marker present.
    Silent,
    /// A marker is present but says nothing — the form without the decision.
    Blank(&'static str),
    /// Both markers present: the file claims an invariant and claims to have none.
    Contradictory,
}

const INVARIANT: &str = "INVARIANT:";
const NO_INVARIANT: &str = "No runtime invariant:";

/// Classify one module from its source text.
///
/// Kept pure and separate from disk walking so the failure branches — including the zero-subject
/// case below — are testable without staging a fake source tree.
fn classify(source: &str) -> Verdict {
    let mut stated = 0usize;
    let mut blank_statement = false;
    let mut justified = false;
    let mut blank_reason = false;

    for line in source.lines() {
        let Some(doc) = line.trim_start().strip_prefix("//!") else { continue };
        let doc = doc.trim();
        // `No runtime invariant:` is checked first: it does not contain the `INVARIANT:` marker
        // (case differs), but checking the more specific form first keeps that independent of the
        // exact spelling either marker takes later.
        if let Some(reason) = doc.strip_prefix(NO_INVARIANT) {
            if reason.trim().is_empty() {
                blank_reason = true;
            } else {
                justified = true;
            }
        } else if let Some(statement) = doc.strip_prefix(INVARIANT) {
            if statement.trim().is_empty() {
                blank_statement = true;
            } else {
                stated += 1;
            }
        }
    }

    match (stated > 0, justified) {
        (true, true) => Verdict::Contradictory,
        (true, false) => Verdict::States(stated),
        (false, true) => Verdict::Justified,
        (false, false) => {
            if blank_statement {
                Verdict::Blank("INVARIANT: with no property after it")
            } else if blank_reason {
                Verdict::Blank("No runtime invariant: with no reason after it")
            } else {
                Verdict::Silent
            }
        }
    }
}

/// Every `.rs` file under `dir`, sorted, so failure output is stable across runs and platforms.
fn rust_files(dir: &Path) -> Vec<PathBuf> {
    let mut found = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(current) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&current) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else if path.extension().is_some_and(|e| e == "rs") {
                found.push(path);
            }
        }
    }
    found.sort();
    found
}

fn src_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("src")
}

#[test]
fn every_module_states_or_justifies_its_invariants() {
    let root = src_dir();
    let files = rust_files(&root);

    // A sweep that observed zero subjects and reported success is a defect class this project has
    // already paid for once. An empty walk here means the layout moved or the walk broke, and either
    // way this test proved nothing — so it fails rather than passing vacuously.
    assert!(
        !files.is_empty(),
        "discovered no .rs files under {} — the audit observed nothing and cannot pass",
        root.display()
    );

    let mut failures = Vec::new();
    let mut stating = 0usize;
    let mut justified = 0usize;

    for path in &files {
        let source = std::fs::read_to_string(path)
            .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
        let name = path.strip_prefix(&root).unwrap_or(path).display().to_string();

        match classify(&source) {
            Verdict::States(_) => stating += 1,
            Verdict::Justified => justified += 1,
            Verdict::Silent => failures.push(format!(
                "  {name}: states neither `//! {INVARIANT} <property>` nor `//! {NO_INVARIANT} <reason>`"
            )),
            Verdict::Blank(what) => failures.push(format!("  {name}: {what}")),
            Verdict::Contradictory => failures.push(format!(
                "  {name}: claims an invariant AND claims to have none — pick one"
            )),
        }
    }

    assert!(
        failures.is_empty(),
        "{} of {} modules have not decided about their invariants:\n{}\n\n\
         Add one of these to the module's `//!` header:\n  \
         //! {INVARIANT} <a falsifiable property this module holds>\n  \
         //! {NO_INVARIANT} <why this module has nothing to assert>\n\n\
         A property is falsifiable: \"a CommandExit result's measured elapsed time must not exceed \
         its declared timeout_secs\" is one, \"sense runs checks\" is a description and is not.",
        failures.len(),
        files.len(),
        failures.join("\n")
    );

    assert_eq!(
        stating + justified,
        files.len(),
        "every counted module lands in exactly one passing class"
    );
}

#[test]
fn a_silent_module_fails() {
    assert_eq!(classify("//! `thing` — does a thing.\npub fn f() {}\n"), Verdict::Silent);
}

#[test]
fn a_stated_invariant_passes_and_is_counted() {
    let source = "//! `thing` — does a thing.\n//! INVARIANT: the count never decreases.\n";
    assert_eq!(classify(source), Verdict::States(1));
}

#[test]
fn several_invariants_are_counted_separately() {
    let source = "//! INVARIANT: one holds.\n//! more prose\n//! INVARIANT: two also holds.\n";
    assert_eq!(classify(source), Verdict::States(2));
}

#[test]
fn a_justification_passes() {
    let source = "//! No runtime invariant: pure type definitions, no behaviour to violate.\n";
    assert_eq!(classify(source), Verdict::Justified);
}

#[test]
fn the_form_without_the_decision_fails() {
    // The whole point of the rule is that it demands a decision. A marker with nothing after it is
    // the ceremony the rule exists to prevent, so it must not be cheaper than saying something.
    assert!(matches!(classify("//! INVARIANT:\n"), Verdict::Blank(_)));
    assert!(matches!(classify("//! No runtime invariant:   \n"), Verdict::Blank(_)));
}

#[test]
fn claiming_both_fails() {
    let source = "//! INVARIANT: something holds.\n//! No runtime invariant: nothing to check.\n";
    assert_eq!(classify(source), Verdict::Contradictory);
}

#[test]
fn a_marker_outside_a_doc_comment_does_not_count() {
    // A mention in ordinary code or a `//` comment is discussion, not a declaration. Only the
    // module's own `//!` header speaks for the module.
    let source = "// INVARIANT: this is a note to a reader, not a claim.\nlet s = \"INVARIANT: x\";\n";
    assert_eq!(classify(source), Verdict::Silent);
}

#[test]
fn the_walk_finds_no_files_in_an_empty_tree() {
    // The zero-subject guard above is only meaningful if `rust_files` can actually return empty.
    // Proving that here keeps the guard from being a branch nothing ever reaches.
    let empty = tempfile::TempDir::new().unwrap();
    assert!(rust_files(empty.path()).is_empty());
}

#[test]
fn the_walk_reaches_nested_directories() {
    // `src/bin/*.rs` only gets audited if the walk recurses; a shallow read_dir would silently
    // exempt exactly the composition roots that most need a stated decision.
    let root = src_dir();
    let files = rust_files(&root);
    assert!(
        files.iter().any(|p| p.parent().is_some_and(|d| d.ends_with("bin"))),
        "the walk must reach src/bin, or those modules are exempt by accident"
    );
}
