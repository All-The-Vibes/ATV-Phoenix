//! Acceptance tests for separate supervisor/child trace chains (Part of #81).
//!
//! The property under test is **containment**: one writer's corruption must not reach another's
//! chain, and the supervisor's record of its own decisions must survive anything a worker does.

use std::fs;

use phoenix::trace_chains::{verify_mission, MissionChains, SUPERVISOR_CHAIN};
use tempfile::TempDir;

fn workspace() -> TempDir {
    TempDir::new().expect("tempdir")
}

#[test]
fn supervisor_and_goals_write_to_distinct_files() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    let paths = [
        chains.supervisor_path(),
        chains.goal_path("g1"),
        chains.goal_path("g2"),
    ];
    assert_eq!(paths[0].file_name().unwrap(), SUPERVISOR_CHAIN);
    assert_ne!(paths[0], paths[1], "the supervisor must not share a chain with a goal");
    assert_ne!(paths[1], paths[2], "two goals must not share a chain");
}

#[test]
fn each_chain_records_only_its_own_writer() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    chains.supervisor().append("schedule", "d0", true, "admit", "g1 admitted").unwrap();
    chains.goal("g1").append("sense", "d1", true, "command_exit", "g1 green").unwrap();
    chains.goal("g2").append("sense", "d2", false, "command_exit", "g2 red").unwrap();
    chains.goal("g2").append("heal", "d3", true, "command_exit", "g2 healed").unwrap();

    assert_eq!(chains.supervisor().read_all().len(), 1);
    assert_eq!(chains.goal("g1").read_all().len(), 1, "g1 must not see g2's rows");
    assert_eq!(chains.goal("g2").read_all().len(), 2);

    let g1_evidence: Vec<String> =
        chains.goal("g1").read_all().into_iter().map(|e| e.evidence).collect();
    assert!(
        g1_evidence.iter().all(|e| e.contains("g1")),
        "attribution must not depend on filtering a shared file, got {g1_evidence:?}"
    );
}

#[test]
fn every_chain_verifies_independently_and_intact() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    chains.supervisor().append("schedule", "d0", true, "admit", "g1").unwrap();
    for i in 0..3 {
        chains.goal("g1").append("sense", &format!("d{i}"), true, "command_exit", "g1-ok").unwrap();
    }
    chains.goal("g2").append("sense", "x", true, "command_exit", "g2-ok").unwrap();

    let result = verify_mission(&chains, &["g1", "g2"]);

    assert!(result.all_ok());
    assert!(result.supervisor_intact());
    assert_eq!(result.supervisor.rows, 1);
    assert_eq!(result.goals.iter().find(|g| g.writer == "g1").unwrap().rows, 3);
    assert!(result.broken_writers().is_empty());
}

#[test]
fn a_corrupt_child_chain_does_not_break_the_supervisor_or_its_siblings() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    chains.supervisor().append("schedule", "d0", true, "admit", "all").unwrap();
    chains.goal("g1").append("sense", "d1", true, "command_exit", "g1-body").unwrap();
    chains.goal("g2").append("sense", "d2", true, "command_exit", "g2-first").unwrap();
    chains.goal("g2").append("sense", "d3", true, "command_exit", "g2-second").unwrap();

    // Tamper g2's first row by editing an evidence VALUE. Deliberately not a field name: renaming a
    // field makes the row unparseable, which today is silently dropped by Trace::read_all and would
    // make this test pass for the wrong reason. See the separately filed trace-parse-drop bug.
    let g2_path = chains.goal_path("g2");
    let content = fs::read_to_string(&g2_path).unwrap();
    fs::write(&g2_path, content.replacen("g2-first", "g2-TAMPERED", 1)).unwrap();

    let result = verify_mission(&chains, &["g1", "g2"]);

    assert!(!result.all_ok(), "the tamper must be detected");
    assert_eq!(result.broken_writers(), vec!["g2"], "only the tampered writer is named");
    assert!(
        result.supervisor_intact(),
        "a worker corrupting its own chain must not cost the supervisor its record of decisions"
    );
    assert!(result.goals.iter().find(|g| g.writer == "g1").unwrap().ok, "g1 is untouched");
}

#[test]
fn a_corrupt_supervisor_chain_does_not_break_the_children() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    chains.supervisor().append("schedule", "d0", true, "admit", "sup-one").unwrap();
    chains.supervisor().append("schedule", "d1", true, "admit", "sup-two").unwrap();
    chains.goal("g1").append("sense", "d2", true, "command_exit", "g1-body").unwrap();

    let sup_path = chains.supervisor_path();
    let content = fs::read_to_string(&sup_path).unwrap();
    fs::write(&sup_path, content.replacen("sup-one", "EDITED", 1)).unwrap();

    let result = verify_mission(&chains, &["g1"]);

    assert!(!result.supervisor_intact());
    assert_eq!(result.broken_writers(), vec!["supervisor"]);
    assert!(
        result.goals.iter().all(|g| g.ok),
        "child evidence stays trustworthy even when the supervisor's own log was edited"
    );
}

#[test]
fn a_broken_chain_names_the_row_it_broke_at() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    for i in 0..4 {
        chains.goal("g1").append("sense", &format!("d{i}"), true, "command_exit", "row").unwrap();
    }
    let path = chains.goal_path("g1");
    let mut lines: Vec<String> = fs::read_to_string(&path).unwrap().lines().map(String::from).collect();
    lines[2] = lines[2].replacen("\"row\"", "\"BENT\"", 1);
    fs::write(&path, lines.join("\n") + "\n").unwrap();

    let result = verify_mission(&chains, &["g1"]);
    let g1 = result.goals.iter().find(|g| g.writer == "g1").unwrap();

    assert!(!g1.ok);
    assert_eq!(g1.broken_at, Some(2), "'the mission is corrupt' is not actionable; a row index is");
}

#[test]
fn multiple_broken_chains_are_all_reported() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    for goal in ["g1", "g2", "g3"] {
        chains.goal(goal).append("sense", "d", true, "command_exit", &format!("{goal}-body")).unwrap();
    }
    for goal in ["g1", "g3"] {
        let p = chains.goal_path(goal);
        let c = fs::read_to_string(&p).unwrap();
        fs::write(&p, c.replacen(&format!("{goal}-body"), "TAMPERED", 1)).unwrap();
    }

    let result = verify_mission(&chains, &["g1", "g2", "g3"]);

    assert_eq!(result.broken_writers(), vec!["g1", "g3"], "one break must not mask another");
}

#[test]
fn a_goal_that_never_wrote_verifies_as_empty_and_intact() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());
    chains.supervisor().append("schedule", "d", true, "admit", "g1").unwrap();

    let result = verify_mission(&chains, &["never-ran"]);

    let g = result.goals.first().unwrap();
    assert!(g.ok, "no rows is not corruption");
    assert_eq!(g.rows, 0);
    assert!(result.all_ok());
}

#[test]
fn goal_ids_cannot_escape_the_chain_directory() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    for hostile in ["../../etc/passwd", "a/b", "..", ".hidden", ""] {
        let path = chains.goal_path(hostile);
        assert_eq!(
            path.parent().unwrap(),
            chains.root(),
            "goal id {hostile:?} escaped the chain directory to {path:?}"
        );
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        assert!(
            !name.contains(".."),
            "traversal survived sanitisation in {name:?} - '.' is excluded from the allowlist so \
             this class cannot exist by construction"
        );
    }
}

#[test]
fn a_hostile_goal_id_still_produces_a_usable_chain() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    chains.goal("a/b").append("sense", "d", true, "command_exit", "ok").unwrap();

    let result = verify_mission(&chains, &["a/b"]);
    assert!(result.all_ok(), "sanitising must not make the chain unwritable or unverifiable");
    assert_eq!(result.goals[0].rows, 1);
}

#[test]
fn colliding_goal_ids_are_detectable_before_they_merge_two_audits() {
    let ws = workspace();
    let chains = MissionChains::in_workspace(ws.path());

    assert!(
        chains.would_collide("a/b", "a:b"),
        "both sanitise to the same filename; a silent merge would reintroduce interleaving"
    );
    assert!(!chains.would_collide("g1", "g2"));
    assert!(!chains.would_collide("g1", "g1"), "a goal does not collide with itself");
}
