//! Acceptance tests for the durable run ledger (shared dependency of #80 and #81).
//!
//! Two properties dominate. The ledger must be **append-only** — history that can be rewritten is
//! not evidence. And a damaged line must be **reported, not skipped**, because a ledger that
//! silently drops corrupt rows reads as merely shorter. That second one is the exact defect filed
//! as #111 against the trace chain, so it gets tested here rather than assumed.

use phoenix::run_artifacts::{RunArtifacts, Usage};
use phoenix::run_ledger::{LedgerEntry, RunLedger, LEDGER_FILE};
use tempfile::TempDir;

fn mission() -> TempDir {
    TempDir::new().expect("tempdir")
}

fn artifacts_ok() -> RunArtifacts {
    RunArtifacts::none_for("copilot_cloud")
        .with_task_id("task-1")
        .with_branch("copilot/fix-1")
        .with_model("gpt-5-codex")
        .with_usage(Usage::with_tokens(100, 50).with_cost(2_500))
}

#[test]
fn a_missing_ledger_reads_as_empty_and_intact() {
    let m = mission();
    let read = RunLedger::in_mission(m.path()).read();

    assert!(read.entries.is_empty());
    assert!(read.is_intact(), "nothing ran is not the same as we cannot say what ran");
}

#[test]
fn the_ledger_lands_at_the_mission_default_path() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &artifacts_ok()).unwrap();

    assert_eq!(l.path().file_name().unwrap(), LEDGER_FILE);
    assert!(l.path().exists());
}

#[test]
fn a_recorded_run_round_trips_every_field() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &artifacts_ok()).unwrap();

    let read = l.read();
    assert_eq!(read.entries.len(), 1);
    let e = &read.entries[0];

    assert_eq!(e.goal, "g1");
    assert_eq!(e.backend, "copilot_cloud");
    assert_eq!(e.task_id.as_deref(), Some("task-1"));
    assert_eq!(e.branch.as_deref(), Some("copilot/fix-1"));
    assert_eq!(e.model.as_deref(), Some("gpt-5-codex"));
    assert_eq!(e.usage().total_tokens(), Some(150));
    assert_eq!(e.cost_micros, Some(2_500));
    assert!(!e.failed());
}

#[test]
fn unreported_usage_survives_the_round_trip_as_unreported() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &RunArtifacts::none_for("local")).unwrap();

    let read = l.read();
    let e = &read.entries[0];

    assert_eq!(e.input_tokens, None);
    assert_eq!(e.output_tokens, None);
    assert_eq!(e.cost_micros, None);
    assert!(
        !e.usage().is_reported(),
        "defaulting to zero on the way to disk would bake 'we did not measure' into 'it was free'"
    );
}

#[test]
fn a_failed_run_records_its_reason_and_its_backend_choice() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record(
        "g1",
        &RunArtifacts::none_for("copilot_cloud").with_error("503 service unavailable"),
    )
    .unwrap();

    let e = &l.read().entries[0];
    assert!(e.failed());
    assert_eq!(e.error.as_deref(), Some("503 service unavailable"));
    assert_eq!(
        e.backend, "copilot_cloud",
        "'we chose cloud and it refused' differs from 'we never chose'"
    );
    assert_eq!(e.task_id, None, "a run that never dispatched has no task id");
}

#[test]
fn appending_preserves_every_earlier_entry_in_order() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    for i in 0..5 {
        l.record(&format!("g{i}"), &RunArtifacts::none_for("local")).unwrap();
    }

    let read = l.read();
    assert_eq!(read.entries.len(), 5);
    let goals: Vec<&str> = read.entries.iter().map(|e| e.goal.as_str()).collect();
    assert_eq!(goals, vec!["g0", "g1", "g2", "g3", "g4"], "append-only means insertion order");
}

#[test]
fn a_second_ledger_handle_appends_rather_than_truncating() {
    let m = mission();
    RunLedger::in_mission(m.path()).record("g1", &RunArtifacts::none_for("local")).unwrap();
    // A fresh handle, as a restarted supervisor would construct.
    RunLedger::in_mission(m.path()).record("g2", &RunArtifacts::none_for("local")).unwrap();

    let read = RunLedger::in_mission(m.path()).read();
    assert_eq!(read.entries.len(), 2, "a restart must not overwrite the record it is resuming");
}

#[test]
fn a_damaged_line_is_reported_not_skipped() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &artifacts_ok()).unwrap();
    l.record("g2", &artifacts_ok()).unwrap();
    l.record("g3", &artifacts_ok()).unwrap();

    // Corrupt the middle line's structure.
    let mut lines: Vec<String> =
        std::fs::read_to_string(l.path()).unwrap().lines().map(String::from).collect();
    lines[1] = "{ this is not valid json".to_string();
    std::fs::write(l.path(), lines.join("\n") + "\n").unwrap();

    let read = l.read();
    assert!(!read.is_intact(), "a corrupt ledger must not read as merely shorter (see #111)");
    assert_eq!(read.unreadable, vec![1], "the damaged line is identified by index");
    assert_eq!(read.entries.len(), 2, "the readable entries are still returned");
}

#[test]
fn a_torn_final_line_from_a_crash_is_visible() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &artifacts_ok()).unwrap();

    // Simulate a process killed mid-write: a partial final record, no newline.
    let mut content = std::fs::read_to_string(l.path()).unwrap();
    content.push_str("{\"goal\":\"g2\",\"backend\":\"loc");
    std::fs::write(l.path(), content).unwrap();

    let read = l.read();
    assert!(!read.is_intact(), "a torn tail must be surfaced, not silently dropped");
    assert_eq!(read.unreadable, vec![1]);
    assert_eq!(read.entries.len(), 1, "the completed record before the crash still counts");
}

#[test]
fn writing_after_a_torn_tail_does_not_merge_records() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &artifacts_ok()).unwrap();

    let read = l.read();
    assert!(read.is_intact());
    assert_eq!(read.entries.len(), 1);

    // Every append ends with a newline, so the next record starts on its own line.
    l.record("g2", &artifacts_ok()).unwrap();
    let after = l.read();
    assert!(after.is_intact(), "records must never merge into one line");
    assert_eq!(after.entries.len(), 2);
}

#[test]
fn total_cost_ignores_unreported_runs_rather_than_counting_them_as_free() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &RunArtifacts::none_for("cloud").with_usage(Usage::default().with_cost(1_000)))
        .unwrap();
    l.record("g2", &RunArtifacts::none_for("local")).unwrap(); // nothing reported
    l.record("g3", &RunArtifacts::none_for("cloud").with_usage(Usage::default().with_cost(500)))
        .unwrap();

    let read = l.read();
    assert_eq!(read.total_cost_micros(), 1_500);
    assert_eq!(read.entries.len(), 3, "the unmeasured run is still recorded, just not costed");
}

#[test]
fn entries_are_queryable_per_goal() {
    let m = mission();
    let l = RunLedger::in_mission(m.path());
    l.record("g1", &RunArtifacts::none_for("local")).unwrap();
    l.record("g2", &RunArtifacts::none_for("cloud")).unwrap();
    l.record("g1", &RunArtifacts::none_for("cloud").with_error("retry failed")).unwrap();

    let read = l.read();
    let g1 = read.for_goal("g1");
    assert_eq!(g1.len(), 2, "a retried goal has more than one run recorded");
    assert!(g1[1].failed());
    assert_eq!(read.for_goal("nobody").len(), 0);
}

#[test]
fn an_entry_built_from_artifacts_matches_the_artifacts() {
    let a = artifacts_ok();
    let e = LedgerEntry::from_artifacts("g1", &a);

    assert_eq!(e.backend, a.backend);
    assert_eq!(e.task_id, a.task_id);
    assert_eq!(e.branch, a.branch);
    assert_eq!(e.model, a.model);
    assert_eq!(e.usage(), a.usage, "usage must carry across unchanged, including its Nones");
}
