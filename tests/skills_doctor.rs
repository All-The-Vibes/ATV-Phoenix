//! Self-maintenance test: Phoenix validates its OWN bundled skills with its own doctor.
//! If any bundled SKILL.md drifts (bad frontmatter, name mismatch), `cargo test` fails — the harness
//! catches its own rot objectively, the same discipline it gives the agent.

use std::path::PathBuf;

fn skills_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("skills")
}

#[test]
fn all_bundled_skills_are_valid() {
    let r = phoenix::doctor(&skills_dir());
    assert!(r.skills_checked >= 6, "expected >=6 bundled skills, found {}", r.skills_checked);
    for s in &r.skills {
        assert!(s.ok, "bundled skill '{}' is invalid: {}", s.name, s.problems.join("; "));
    }
    assert!(r.ok, "phoenix doctor reported skills not OK");
}

#[test]
fn doctor_catches_a_broken_skill() {
    // good
    let good = phoenix::doctor::check_skill_file(
        "phoenix-spec",
        "---\nname: phoenix-spec\ndescription: this description is definitely long enough to pass the check\n---\nbody",
    );
    assert!(good.ok, "good skill should pass: {:?}", good.problems);

    // name mismatch
    let bad = phoenix::doctor::check_skill_file(
        "phoenix-spec",
        "---\nname: wrong-name\ndescription: this description is definitely long enough to pass the check\n---\nbody",
    );
    assert!(!bad.ok, "name mismatch must fail");

    // missing description
    let bad2 = phoenix::doctor::check_skill_file("x", "---\nname: x\n---\nbody");
    assert!(!bad2.ok, "missing description must fail");
}
