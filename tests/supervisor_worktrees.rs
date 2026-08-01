//! Acceptance tests for mandatory worktree isolation (Part of #81).
//!
//! The failure this prevents is nasty precisely because it is intermittent: two goals building in
//! one checkout interleave their edits, and the resulting test failure is attributed to whichever
//! goal ran last. So the tests below hammer one question — can two goals ever end up pointed at the
//! same directory, by any route?

use std::path::PathBuf;

use phoenix::worktrees::{AssignmentDenied, WorktreeRegistry, WORKTREE_PREFIX};

fn registry() -> WorktreeRegistry {
    WorktreeRegistry::new(PathBuf::from("/missions/m1"))
}

#[test]
fn an_assigned_goal_gets_a_path_under_the_root() {
    let mut r = registry();
    let path = r.assign("g1").expect("a fresh goal is assignable");

    assert_eq!(path.parent().unwrap(), r.root());
    assert!(
        path.file_name().unwrap().to_string_lossy().starts_with(WORKTREE_PREFIX),
        "got {path:?}"
    );
    assert_eq!(r.assigned("g1"), Some(path.as_path()));
}

#[test]
fn two_goals_never_share_a_worktree() {
    let mut r = registry();
    let a = r.assign("g1").unwrap();
    let b = r.assign("g2").unwrap();

    assert_ne!(a, b, "interleaved builds in one checkout produce misattributed failures");
    assert!(r.all_paths_distinct());
}

#[test]
fn a_goal_cannot_be_assigned_twice() {
    let mut r = registry();
    let first = r.assign("g1").unwrap();

    match r.assign("g1") {
        Err(AssignmentDenied::AlreadyAssigned { existing }) => assert_eq!(existing, first),
        other => panic!("expected AlreadyAssigned, got {other:?}"),
    }
}

#[test]
fn the_idempotent_form_returns_the_existing_assignment() {
    let mut r = registry();
    let first = r.assign_or_existing("g1").unwrap();
    let again = r.assign_or_existing("g1").unwrap();

    assert_eq!(first, again, "a retry must not fail merely because the first attempt worked");
    assert_eq!(r.assignments().len(), 1, "and must not create a second entry");
}

#[test]
fn a_colliding_goal_id_is_refused_not_silently_shared() {
    let mut r = registry();
    // Distinct ids that sanitise to the same directory name.
    let first = r.assign("a/b").unwrap();

    match r.assign("a:b") {
        Err(AssignmentDenied::PathTaken { holder, path }) => {
            assert_eq!(holder, "a/b", "the refusal must name who already holds it");
            assert_eq!(path, first);
        }
        other => panic!("a collision must be refused, not shared - got {other:?}"),
    }
    assert!(r.all_paths_distinct());
}

#[test]
fn the_idempotent_form_still_refuses_a_genuine_collision() {
    let mut r = registry();
    r.assign("a/b").unwrap();

    assert!(
        matches!(r.assign_or_existing("a:b"), Err(AssignmentDenied::PathTaken { .. })),
        "idempotence must not become permission to share another goal's workspace"
    );
}

#[test]
fn a_goal_may_not_execute_without_an_assignment() {
    let mut r = registry();

    assert!(!r.may_execute("g1"), "no workspace means no mandate to build");
    r.assign("g1").unwrap();
    assert!(r.may_execute("g1"));
}

#[test]
fn releasing_frees_the_path_for_another_goal() {
    let mut r = registry();
    let path = r.assign("a/b").unwrap();
    assert!(matches!(r.assign("a:b"), Err(AssignmentDenied::PathTaken { .. })));

    assert!(r.release("a/b"));
    assert!(!r.may_execute("a/b"), "a released goal loses its mandate to build");

    let reused = r.assign("a:b").expect("the freed path is assignable again");
    assert_eq!(reused, path);
}

#[test]
fn releasing_an_unassigned_goal_reports_false() {
    let mut r = registry();
    assert!(!r.release("never-assigned"));

    r.assign("g1").unwrap();
    assert!(r.release("g1"));
    assert!(!r.release("g1"), "releasing twice must not report success the second time");
}

#[test]
fn a_release_does_not_disturb_other_goals() {
    let mut r = registry();
    let g1 = r.assign("g1").unwrap();
    let g2 = r.assign("g2").unwrap();

    r.release("g1");

    assert_eq!(r.assigned("g2"), Some(g2.as_path()), "g2 keeps its workspace");
    assert!(r.may_execute("g2"));
    assert_ne!(g1, g2);
}

#[test]
fn hostile_goal_ids_cannot_escape_the_root() {
    let r = registry();

    for hostile in ["../../etc", "a/b", "..", ".hidden", "", "C:\\Windows"] {
        let path = r.path_for(hostile);
        assert_eq!(
            path.parent().unwrap(),
            r.root(),
            "goal id {hostile:?} escaped the root to {path:?}"
        );
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        assert!(
            !name.contains(".."),
            "'.' is excluded from the allowlist, so '..' cannot appear - got {name:?}"
        );
    }
}

#[test]
fn path_for_is_pure_and_does_not_reserve() {
    let mut r = registry();
    let peeked = r.path_for("g1");

    assert!(r.assigned("g1").is_none(), "asking must not reserve");
    assert!(!r.may_execute("g1"));

    let assigned = r.assign("g1").unwrap();
    assert_eq!(peeked, assigned, "the peek must predict the real assignment");
}

#[test]
fn many_goals_all_receive_distinct_paths() {
    let mut r = registry();
    for i in 0..25 {
        r.assign(&format!("goal-{i}")).expect("distinct ids are all assignable");
    }

    assert_eq!(r.assignments().len(), 25);
    assert!(r.all_paths_distinct(), "no two of 25 parallel workers may share a checkout");
}
