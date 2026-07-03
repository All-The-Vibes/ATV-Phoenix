//! Composite intent-accept tests — proves the N-goal gate logic.
//!
//! Gate behaviour under test:
//!   A. All goals proven failure-first → composite ok=true
//!   B. Even one goal not proven       → composite ok=false
//!   C. Goal count > MAX_GOALS         → composite ok=false (ceiling guard)
//!   D. Empty goal list                → composite ok=false
//!   E. Vacuous goal (never red)       → composite ok=false (inherits single-goal rule)

use phoenix::intent::{verify_intent, GoalSpec, IntentManifest, MAX_GOALS};
use phoenix::sense::{canonical_digest, Check};
use phoenix::Trace;
use std::path::{Path, PathBuf};

fn tmp_ws(name: &str) -> PathBuf {
    let mut dir = std::env::temp_dir();
    dir.push(format!("phoenix_intent_{}_{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join(".phoenix")).unwrap();
    dir
}

fn regex_check(file: &Path, pat: &str) -> Check {
    serde_json::from_str(&format!(
        r#"{{"kind":"regex_in_file","target":["{}"],"expect":"{}"}}"#,
        file.display().to_string().replace('\\', "\\\\"),
        pat
    ))
    .unwrap()
}

fn make_goal(id: &str, title: &str, check: Check) -> GoalSpec {
    GoalSpec { id: id.to_string(), title: title.to_string(), check, depends_on: vec![], kind: None }
}

/// Simulate a completed goal: append RED then GREEN to the per-goal trace, with matching file state.
fn prove_goal(ws: &Path, goal: &GoalSpec, sentinel: &Path, content_red: &str, content_green: &str) {
    let goal_ws = ws.join(".phoenix-intent").join(&goal.id);
    std::fs::create_dir_all(goal_ws.join(".phoenix")).unwrap();
    let tr = Trace::default_in(&goal_ws);
    let digest = canonical_digest(&goal.check);
    std::fs::write(sentinel, content_red).unwrap();
    tr.append("sense", &digest, false, "regex_in_file", "red").unwrap();
    std::fs::write(sentinel, content_green).unwrap();
    tr.append("sense", &digest, true, "regex_in_file", "green").unwrap();
}

// --- A: all goals proven → composite ok -------------------------------------

#[test]
fn all_goals_proven_composite_ok() {
    let ws = tmp_ws("all_ok");
    let out1 = ws.join("goal1.txt");
    let out2 = ws.join("goal2.txt");
    let check1 = regex_check(&out1, "DONE1");
    let check2 = regex_check(&out2, "DONE2");

    let goals = vec![
        make_goal("goal-1", "First goal", check1.clone()),
        make_goal("goal-2", "Second goal", check2.clone()),
    ];
    let manifest = IntentManifest { intent: "test intent".into(), goals };

    prove_goal(&ws, &manifest.goals[0], &out1, "working1", "DONE1");
    prove_goal(&ws, &manifest.goals[1], &out2, "working2", "DONE2");

    let result = verify_intent(&ws, &manifest);
    assert!(result.ok, "all goals proven → composite should be ok: {}", result.reason);
    assert_eq!(result.goals_ok, 2);
    assert_eq!(result.goal_count, 2);
    assert!(result.goals.iter().all(|g| g.gate.ok));

    let _ = std::fs::remove_dir_all(&ws);
}

// --- B: one unproven goal → composite fails ---------------------------------

#[test]
fn one_unproven_goal_fails_composite() {
    let ws = tmp_ws("one_fail");
    let out1 = ws.join("goal1.txt");
    let out2 = ws.join("goal2.txt");
    let check1 = regex_check(&out1, "DONE1");
    let check2 = regex_check(&out2, "DONE2");

    let goals = vec![
        make_goal("goal-a", "Proven goal", check1.clone()),
        make_goal("goal-b", "Unproven goal", check2.clone()),
    ];
    let manifest = IntentManifest { intent: "partial intent".into(), goals };

    // Only prove goal-a; leave goal-b with an empty per-goal trace and a RED file state.
    prove_goal(&ws, &manifest.goals[0], &out1, "working1", "DONE1");
    std::fs::write(&out2, "not-done").unwrap();
    // goal-b trace is empty (no sense events) → not proven

    let result = verify_intent(&ws, &manifest);
    assert!(!result.ok, "one unproven goal → composite should fail");
    assert_eq!(result.goals_ok, 1);
    assert!(result.goals[0].gate.ok);
    assert!(!result.goals[1].gate.ok);
    assert!(!result.goals[1].gate.saw_red, "no trace events → saw_red=false");

    let _ = std::fs::remove_dir_all(&ws);
}

// --- C: goal count > MAX_GOALS → ceiling guard ------------------------------

#[test]
fn goal_count_ceiling_rejects_over_max() {
    let ws = tmp_ws("over_max");
    let out = ws.join("x.txt");
    let check = regex_check(&out, "DONE");
    // MAX_GOALS+1 goals — intentionally one over the ceiling to trigger the guard
    let goals: Vec<GoalSpec> =
        (0..(MAX_GOALS + 1)).map(|i| make_goal(&format!("goal-{i}"), &format!("Goal {i}"), check.clone())).collect();

    let manifest = IntentManifest { intent: "too many goals".into(), goals };
    let result = verify_intent(&ws, &manifest);

    assert!(!result.ok);
    assert!(result.reason.contains("ceiling"), "reason should mention ceiling: {}", result.reason);
    assert_eq!(result.goals.len(), 0, "ceiling guard returns before evaluating goals");

    let _ = std::fs::remove_dir_all(&ws);
}

// --- D: empty goal list → rejected ------------------------------------------

#[test]
fn empty_goals_rejected() {
    let ws = tmp_ws("empty");
    let manifest = IntentManifest { intent: "no goals".into(), goals: vec![] };
    let result = verify_intent(&ws, &manifest);
    assert!(!result.ok);
    assert_eq!(result.goal_count, 0);
    let _ = std::fs::remove_dir_all(&ws);
}

// --- E: vacuous goal (never red) → not accepted -----------------------------

#[test]
fn vacuous_goal_never_red_not_accepted() {
    let ws = tmp_ws("vacuous");
    let out = ws.join("goal.txt");
    let check = regex_check(&out, "DONE");
    let goals = vec![make_goal("vacuous-goal", "Vacuous goal (never red)", check.clone())];
    let manifest = IntentManifest { intent: "vacuous intent".into(), goals };

    // Write green state but record ONLY a green event — no RED ever observed.
    std::fs::write(&out, "DONE").unwrap();
    let goal_ws = ws.join(".phoenix-intent").join("vacuous-goal");
    std::fs::create_dir_all(goal_ws.join(".phoenix")).unwrap();
    let tr = Trace::default_in(&goal_ws);
    let digest = canonical_digest(&check);
    tr.append("sense", &digest, true, "regex_in_file", "green-only").unwrap();

    let result = verify_intent(&ws, &manifest);
    assert!(!result.ok, "vacuous (never-red) goal must not be accepted");
    assert!(!result.goals[0].gate.saw_red);
    assert!(result.goals[0].gate.currently_green, "it IS green now");

    let _ = std::fs::remove_dir_all(&ws);
}

// --- F: per-goal traces are isolated (different workspaces) -----------------

#[test]
fn per_goal_traces_are_isolated() {
    // Proves that proving goal-1 does NOT affect goal-2's trace, and goal-2 must be
    // proven independently. Isolation is the whole point of per-goal workspaces.
    let ws = tmp_ws("isolated");
    let out1 = ws.join("sentinel1.txt");
    let out2 = ws.join("sentinel2.txt");
    let check1 = regex_check(&out1, "GREEN1");
    let check2 = regex_check(&out2, "GREEN2");

    let goals = vec![
        make_goal("iso-goal-1", "Isolated goal 1", check1.clone()),
        make_goal("iso-goal-2", "Isolated goal 2", check2.clone()),
    ];
    let manifest = IntentManifest { intent: "isolation test".into(), goals };

    // Prove only goal 1.
    prove_goal(&ws, &manifest.goals[0], &out1, "red1", "GREEN1");
    // goal 2 file is green but trace is empty.
    std::fs::write(&out2, "GREEN2").unwrap();

    let result = verify_intent(&ws, &manifest);
    assert!(!result.ok, "goal-2 not proven → composite fails");
    assert!(result.goals[0].gate.ok, "goal-1 is proven");
    assert!(!result.goals[1].gate.ok, "goal-2 is not proven (no trace events)");

    let _ = std::fs::remove_dir_all(&ws);
}
