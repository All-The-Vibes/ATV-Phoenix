use std::process::Command;

use phoenix::run_ledger::RunLedger;
use phoenix::trace_chains::{MissionChains, verify_mission};

#[test]
fn mission_cli_runs_diamond_and_writes_verifiable_chains() {
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

    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("mission completed with backend=local"));

    let goals = ["a", "b", "c", "d"];
    for goal in goals {
        assert!(stdout.contains(&format!("goal {goal} chain_ok=true")), "missing chain output for {goal}");
    }

    let chains = MissionChains::in_workspace(workspace.path());
    let verify = verify_mission(&chains, &["a", "b", "c", "d"]);
    assert!(verify.all_ok(), "trace verification failed: {:?}", verify.broken_writers());

    let ledger = RunLedger::in_mission(workspace.path()).read();
    assert!(ledger.is_intact());
    assert_eq!(ledger.entries.len(), 4, "diamond DAG should execute all 4 goals");
    for goal in ["a", "b", "c", "d"] {
        assert_eq!(ledger.for_goal(goal).len(), 1, "expected one ledger entry for {goal}");
    }
}
