//! Install-integrity tests for `doctor`. The headline case is a regression gate on the real bug a
//! community user hit: a `phoenix.agent.md` whose inline MCP server was missing `args:` — the Copilot
//! CLI schema requires it, so the agent silently failed to load. `doctor` must catch that GENERICALLY
//! (as drift from the shipped template, with no per-field knowledge of `args`) and `--fix` must repair
//! it so the installed file matches what this build ships.

use std::fs;
use std::path::Path;

/// Build a temp Copilot home with a given agent file body and the full set of shipped skills + a valid
/// mcp-config, so only the agent under test is "wrong".
fn seed_home(dir: &Path, agent_body: &str, bin: &str) {
    let agents = dir.join("agents");
    fs::create_dir_all(&agents).unwrap();
    fs::write(agents.join("phoenix.agent.md"), agent_body).unwrap();

    let skills = dir.join("skills");
    for (name, content) in phoenix::doctor::shipped_skills() {
        let d = skills.join(name);
        fs::create_dir_all(&d).unwrap();
        fs::write(d.join("SKILL.md"), content).unwrap();
    }

    let cfg = format!(
        "{{\n  \"mcpServers\": {{\n    \"phoenix\": {{\n      \"type\": \"stdio\",\n      \"command\": \"{}\"\n    }}\n  }}\n}}\n",
        bin.replace('\\', "/")
    );
    fs::write(dir.join("mcp-config.json"), cfg).unwrap();
}

/// The shipped template with the `args:` line removed — i.e., exactly the pre-fix broken agent file.
fn broken_agent_without_args(bin: &str) -> String {
    let shipped = phoenix::doctor::shipped_agent_template().replace("__PHOENIX_BIN__", bin);
    shipped
        .lines()
        .filter(|l| l.trim() != "args: []")
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn doctor_catches_missing_args_agent_as_drift() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    // a real-looking binary path that exists, so ONLY the agent content is wrong
    let bin = std::env::current_exe().unwrap();
    let bin_s = bin.display().to_string();

    let broken = broken_agent_without_args(&bin_s);
    assert!(!broken.contains("args: []"), "fixture must be the pre-fix broken file");
    seed_home(home, &broken, &bin_s);

    let report = phoenix::integrity(home);
    let agent = report.checks.iter().find(|c| c.check == "agent").unwrap();
    assert!(!agent.ok, "doctor must flag the missing-args agent as drifted");
    assert!(!report.ok, "overall report must be red");
    // GENERIC: the detector must not name the specific field; it catches it purely as drift.
    let src = include_str!("../src/doctor.rs");
    assert!(
        !src.contains("\"args\"") && !src.contains("args: []"),
        "doctor must not hardcode the `args` field — it should catch this generically as drift"
    );
}

#[test]
fn fix_repairs_broken_agent_to_match_shipped() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    let bin = std::env::current_exe().unwrap();
    let bin_s = bin.display().to_string();

    seed_home(home, &broken_agent_without_args(&bin_s), &bin_s);
    assert!(!phoenix::integrity(home).ok, "precondition: install is broken");

    let actions = phoenix::doctor_fix(home, &bin);
    assert!(
        actions.iter().any(|a| a.contains("agent")),
        "fix should report re-syncing the agent, got: {actions:?}"
    );

    let after = phoenix::integrity(home);
    assert!(after.ok, "after --fix the install must be green: {:?}", after.checks);

    // the repaired file now contains the shipped args line again, and matches the template
    let repaired = fs::read_to_string(home.join("agents").join("phoenix.agent.md")).unwrap();
    assert!(repaired.contains("args: []"), "repaired agent should carry the shipped args line");
}

#[test]
fn fix_is_idempotent() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    let bin = std::env::current_exe().unwrap();

    // first fix builds a clean install from nothing
    phoenix::doctor_fix(home, &bin);
    assert!(phoenix::integrity(home).ok, "first fix should produce a green install");

    // second fix must change nothing and stay green
    let actions = phoenix::doctor_fix(home, &bin);
    assert!(actions.is_empty(), "second fix should be a no-op, got: {actions:?}");
    assert!(phoenix::integrity(home).ok, "still green after a second fix");
}

#[test]
fn doctor_flags_missing_skill_and_unregistered_mcp() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    let bin = std::env::current_exe().unwrap();
    let bin_s = bin.display().to_string();

    // valid agent, valid skills, valid mcp...
    let good_agent = phoenix::doctor::shipped_agent_template().replace("__PHOENIX_BIN__", &bin_s);
    seed_home(home, &good_agent, &bin_s);
    assert!(phoenix::integrity(home).ok, "baseline should be green");

    // ...then break two independent things
    let first_skill = phoenix::doctor::shipped_skills()[0].0;
    fs::remove_dir_all(home.join("skills").join(first_skill)).unwrap();
    fs::remove_file(home.join("mcp-config.json")).unwrap();

    let report = phoenix::integrity(home);
    let skills = report.checks.iter().find(|c| c.check == "skills").unwrap();
    let mcp = report.checks.iter().find(|c| c.check == "mcp-config").unwrap();
    assert!(!skills.ok, "missing skill must be flagged");
    assert!(!mcp.ok, "missing mcp registration must be flagged");

    // and fix heals both
    phoenix::doctor_fix(home, &bin);
    assert!(phoenix::integrity(home).ok, "fix should restore the missing skill and re-register mcp");
}
