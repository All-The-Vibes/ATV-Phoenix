//! Issue #145: `phoenix-mcp sense` and `phoenix-mcp accept` panicked when invoked with no
//! argument, because each verb indexed `args[2]` with no length guard. A panic exits 101, which
//! is non-zero, so an exit-code-only check would pass against the broken binary. This test also
//! asserts the no-panic property and that stdout carries a machine-readable `ok:false` result
//! with a `reason`, which the loop driver parses.

use std::process::Command;

/// Run the binary with a single subcommand and no JSON argument.
fn run_missing_arg(subcommand: &str) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_phoenix-mcp"))
        .arg(subcommand)
        .output()
        .expect("spawn phoenix-mcp")
}

fn assert_usage_not_panic(subcommand: &str) {
    let out = run_missing_arg(subcommand);
    let stdout = String::from_utf8_lossy(&out.stdout);
    let stderr = String::from_utf8_lossy(&out.stderr);

    // 1. No panic: the whole point of the fix.
    assert!(
        !stderr.contains("panicked at"),
        "{subcommand}: stderr shows a panic, guard is missing:\n{stderr}"
    );

    // 2. Non-zero exit. On its own this is not enough (the panic also exits non-zero), which is
    //    why assertion 3 exists.
    assert!(
        !out.status.success(),
        "{subcommand}: expected a non-zero exit. stdout={stdout:?} stderr={stderr:?}"
    );

    // 3. Load-bearing: stdout is one JSON object carrying ok:false and a `reason` that names the
    //    subcommand and the word "usage". A panic writes nothing to stdout, so this fails against
    //    the unfixed binary.
    let value: serde_json::Value = serde_json::from_str(stdout.trim())
        .unwrap_or_else(|e| panic!("{subcommand}: stdout is not JSON ({e}): {stdout:?}"));
    assert_eq!(
        value.get("ok").and_then(serde_json::Value::as_bool),
        Some(false),
        "{subcommand}: result must carry ok:false, got {stdout}"
    );
    let reason = value
        .get("reason")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_else(|| panic!("{subcommand}: result has no string `reason`: {stdout}"));
    assert!(
        reason.contains(subcommand) && reason.contains("usage"),
        "{subcommand}: `reason` must name the subcommand and \"usage\": {reason:?}"
    );
}

#[test]
fn sense_without_argument_reports_usage_not_panic() {
    assert_usage_not_panic("sense");
}

#[test]
fn accept_without_argument_reports_usage_not_panic() {
    assert_usage_not_panic("accept");
}