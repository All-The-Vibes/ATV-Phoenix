use std::fs;
use std::process::Command;

use phoenix::run_ledger::RunLedger;
use phoenix::trace_chains::{MissionChains, verify_mission};

#[test]
fn mission_cli_calls_library_root_and_emits_verifiable_artifacts() {
    let source = fs::read_to_string("src/bin/phoenix_mission.rs").expect("read mission cli source");
    assert!(
        !source.contains("fn run_mission("),
        "binary must not define a local run_mission; it must call phoenix::mission::run_mission"
    );
    assert!(
        source.contains("phoenix::mission::{MissionConfig, run_mission}"),
        "binary must import and use phoenix::mission::run_mission composition root"
    );

    let workspace = tempfile::tempdir().expect("tempdir");
    let bin = env!("CARGO_BIN_EXE_phoenix_mission");
    let output = Command::new(bin)
        .arg("--workspace")
        .arg(workspace.path())
        .output()
        .expect("run phoenix_mission");

    assert!(
        output.status.success(),
        "mission cli failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let ledger = RunLedger::in_mission(workspace.path()).read();
    assert!(ledger.is_intact(), "run ledger must be intact");
    assert_eq!(ledger.entries.len(), 4, "diamond DAG should execute all 4 goals");
    for goal in ["a", "b", "c", "d"] {
        assert_eq!(ledger.for_goal(goal).len(), 1, "expected one ledger entry for {goal}");
    }

    let chains = MissionChains::in_workspace(workspace.path());
    let verify = verify_mission(&chains, &["a", "b", "c", "d"]);
    assert!(verify.supervisor.ok, "supervisor chain must verify");
    for goal_chain in &verify.goals {
        assert!(goal_chain.ok, "goal chain {:?} must verify", goal_chain.writer);
    }
    assert!(verify.all_ok(), "all chains must verify");
}
