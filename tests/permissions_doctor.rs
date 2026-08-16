//! Per-folder MCP-approval tests for `doctor --permissions`. The bug this gates: phoenix can be
//! REGISTERED (mcp-config.json) yet UNAPPROVED for the working folder (permissions-config.json), so
//! a non-interactive host denies `phoenix_sense` with "could not request permission from user" and
//! the harness silently stalls. `check_permissions` must flag that gap, and `fix_permissions` must
//! approve every phoenix tool for the folder — idempotently, preserving unrelated approvals, with a
//! backup of the prior config (heal discipline).

use std::fs;
use std::path::Path;

fn write_cfg(home: &Path, body: &str) {
    fs::write(home.join("permissions-config.json"), body).unwrap();
}

#[test]
fn red_when_permissions_config_missing() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    let cwd = Path::new("C:/proj/demo");
    let r = phoenix::doctor::check_permissions(home, cwd);
    assert!(!r.ok, "a missing permissions-config must be RED");
    assert!(r.fixable, "the approval gap is fixable");
}

#[test]
fn red_when_phoenix_not_approved_for_this_folder() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    let cwd = Path::new("C:/proj/demo");
    // The config exists and approves a DIFFERENT server for this folder, and approves phoenix only
    // for ANOTHER folder — so phoenix is unapproved HERE.
    write_cfg(
        home,
        r#"{"locations":{
            "C:/proj/demo":{"tool_approvals":[{"kind":"mcp","serverName":"workiq","toolName":"ask_work_iq"}]},
            "C:/other":{"tool_approvals":[{"kind":"mcp","serverName":"phoenix","toolName":"phoenix_sense"}]}
        }}"#,
    );
    let r = phoenix::doctor::check_permissions(home, cwd);
    assert!(!r.ok, "phoenix unapproved for THIS folder must be RED");
    assert!(
        r.problems.iter().any(|p| p.contains("NOT approved")),
        "remediation must name the unapproved-server case, got: {:?}",
        r.problems
    );
}

#[test]
fn fix_approves_all_phoenix_tools_idempotently() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    let cwd = Path::new("C:/proj/demo");
    write_cfg(home, r#"{"locations":{}}"#);
    assert!(
        !phoenix::doctor::check_permissions(home, cwd).ok,
        "precondition: RED before fix"
    );

    let actions = phoenix::doctor::fix_permissions(home, cwd);
    assert!(!actions.is_empty(), "fix should report approvals, got {actions:?}");

    let after = phoenix::doctor::check_permissions(home, cwd);
    assert!(after.ok, "after --fix the approval must be GREEN: {:?}", after.problems);

    // heal discipline: the prior config was snapshotted before the write.
    assert!(
        home.join("permissions-config.json.doctor-bak").exists(),
        "fix must back up the prior permissions-config"
    );

    // all five phoenix tools are approved for this exact folder.
    let written: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(home.join("permissions-config.json")).unwrap()).unwrap();
    let arr = written["locations"]["C:/proj/demo"]["tool_approvals"]
        .as_array()
        .unwrap();
    assert_eq!(arr.len(), 5, "all five phoenix tools approved, got {arr:?}");

    // a second fix is a no-op and stays GREEN.
    let again = phoenix::doctor::fix_permissions(home, cwd);
    assert!(again.is_empty(), "second fix should be a no-op, got {again:?}");
    assert!(
        phoenix::doctor::check_permissions(home, cwd).ok,
        "still GREEN after a second fix"
    );
}

#[test]
fn fix_preserves_unrelated_approvals() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path();
    let cwd = Path::new("C:/proj/demo");
    write_cfg(
        home,
        r#"{"locations":{
            "C:/proj/demo":{"tool_approvals":[{"kind":"mcp","serverName":"workiq","toolName":"ask_work_iq"}]},
            "C:/unrelated":{"tool_approvals":[{"kind":"shell","command":"git status"}]}
        }}"#,
    );
    phoenix::doctor::fix_permissions(home, cwd);
    let written: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(home.join("permissions-config.json")).unwrap()).unwrap();

    // the unrelated location is untouched
    assert!(
        written["locations"]["C:/unrelated"]["tool_approvals"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["command"] == "git status"),
        "unrelated location's approvals must be preserved"
    );
    // the pre-existing workiq approval for this folder is kept alongside the new phoenix ones
    let here = written["locations"]["C:/proj/demo"]["tool_approvals"]
        .as_array()
        .unwrap();
    assert!(
        here.iter().any(|a| a["serverName"] == "workiq"),
        "existing folder approvals must be preserved"
    );
    assert_eq!(
        here.iter().filter(|a| a["serverName"] == "phoenix").count(),
        5,
        "all phoenix tools added without dropping the existing approval"
    );
}
