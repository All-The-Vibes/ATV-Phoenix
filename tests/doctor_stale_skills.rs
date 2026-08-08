//! Doctor must notice skills it installed once and no longer ships.
//!
//! Done-check: `cargo test --locked --test doctor_stale_skills`
//!
//! `check_skills_integrity` iterated only `shipped_skills()`, so a skill dropped in a later
//! version stayed on disk indefinitely while doctor reported "N/N match shipped". The agent kept
//! being offered a superseded skill, competing for routing against the flow that replaced it, and
//! nothing in the health report ever said so. (`phoenix-spec` sat installed this way after being
//! removed upstream in 5ceb518.)
//!
//! These tests pin three properties: stale skills are reported, `--fix` retires them somewhere
//! recoverable and OUTSIDE the skills tree, and unrelated third-party skills are never touched.

use std::fs;
use std::path::Path;

use phoenix::doctor;

/// Build a fake Copilot home with the given skill directories present.
fn home_with_skills(names: &[&str]) -> tempfile::TempDir {
    let home = tempfile::tempdir().unwrap();
    let skills = home.path().join("skills");
    for name in names {
        let dir = skills.join(name);
        fs::create_dir_all(&dir).unwrap();
        fs::write(
            dir.join("SKILL.md"),
            format!("---\nname: {name}\ndescription: placeholder\nlicense: MIT\n---\n\n# {name}\n"),
        )
        .unwrap();
    }
    home
}

fn shipped_names() -> Vec<String> {
    doctor::shipped_skills().iter().map(|(n, _)| n.to_string()).collect()
}

/// Install every shipped skill verbatim so only the stale one can be the finding.
fn install_all_shipped(home: &Path) {
    let skills = home.join("skills");
    for (name, content) in doctor::shipped_skills() {
        let dir = skills.join(name);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("SKILL.md"), content).unwrap();
    }
}

#[test]
fn a_skill_that_is_installed_but_no_longer_shipped_is_reported() {
    let home = home_with_skills(&["phoenix-spec"]);
    install_all_shipped(home.path());

    let report = doctor::check_skills_integrity(home.path());

    assert!(!report.ok, "a stale skill must make the skills check red: {report:?}");
    assert!(
        report.problems.iter().any(|p| p.contains("stale") && p.contains("phoenix-spec")),
        "the problem must name the stale skill so it can be acted on: {:?}",
        report.problems
    );
    assert!(
        report.evidence.contains("stale"),
        "the evidence headline must disclose the stale skill instead of reading as a clean match: {}",
        report.evidence
    );
}

#[test]
fn third_party_skills_are_never_claimed_as_stale() {
    // The skills directory is shared. Phoenix has no authority over anything it did not ship.
    let home = home_with_skills(&["azure-deploy", "pptx", "hyperframes-core", "token-master"]);
    install_all_shipped(home.path());

    let report = doctor::check_skills_integrity(home.path());

    assert!(
        report.ok,
        "unrelated third-party skills must not be reported as stale: {:?}",
        report.problems
    );
}

#[test]
fn fix_retires_the_stale_skill_outside_the_skills_tree() {
    let home = home_with_skills(&["phoenix-spec"]);
    install_all_shipped(home.path());

    let actions = doctor::fix(home.path(), Path::new("C:/fake/phoenix-mcp.exe"));

    assert!(
        actions.iter().any(|a| a.contains("phoenix-spec")),
        "fix must report what it retired: {actions:?}"
    );

    let skills = home.path().join("skills");
    assert!(
        !skills.join("phoenix-spec").exists(),
        "the stale skill must be gone from the skills tree"
    );

    // Recoverable, but somewhere it cannot be routed to or re-detected.
    let retired = home.path().join("retired-skills").join("phoenix-spec").join("SKILL.md");
    assert!(retired.exists(), "the retired skill must be kept for recovery at {retired:?}");

    // No leftover inside skills/ that would match the stale scan again next run.
    let leftovers: Vec<String> = fs::read_dir(&skills)
        .unwrap()
        .flatten()
        .filter_map(|e| e.file_name().into_string().ok())
        .filter(|n| n.contains("phoenix-spec"))
        .collect();
    assert!(leftovers.is_empty(), "nothing phoenix-spec-shaped may remain in skills/: {leftovers:?}");
}

#[test]
fn fix_is_idempotent_and_reaches_green() {
    let home = home_with_skills(&["phoenix-spec"]);
    install_all_shipped(home.path());

    doctor::fix(home.path(), Path::new("C:/fake/phoenix-mcp.exe"));
    let after_first = doctor::check_skills_integrity(home.path());
    assert!(after_first.ok, "one fix must clear the finding: {:?}", after_first.problems);

    // A second pass must find nothing left to do — the retirement must not re-detect itself.
    let second = doctor::fix(home.path(), Path::new("C:/fake/phoenix-mcp.exe"));
    assert!(
        !second.iter().any(|a| a.contains("retired")),
        "the retired copy must not be rediscovered as stale: {second:?}"
    );

    let after_second = doctor::check_skills_integrity(home.path());
    assert!(after_second.ok, "doctor must stay green: {:?}", after_second.problems);
}

#[test]
fn a_clean_install_reports_no_stale_skills() {
    let home = tempfile::tempdir().unwrap();
    install_all_shipped(home.path());

    let report = doctor::check_skills_integrity(home.path());
    assert!(report.ok, "a faithful install must be green: {:?}", report.problems);
    assert!(
        report.evidence.contains(&format!("{}/{}", shipped_names().len(), shipped_names().len())),
        "evidence should report a full match: {}",
        report.evidence
    );
}
