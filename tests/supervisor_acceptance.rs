use phoenix::budget::{BudgetLedger, Limits};
use phoenix::lease::{Fence, LeaseRegistry};
use phoenix::lifecycle::Lifecycle;
use phoenix::reconcile::reconcile;
use phoenix::run_artifacts::RunArtifacts;
use phoenix::run_ledger::RunLedger;
use phoenix::supervisor::{Admission, Supervisor};
use phoenix::trace_chains::{verify_mission, MissionChains};
use phoenix::worktrees::WorktreeRegistry;

#[test]
fn supervisor_done_check_exercises_spine_components() {
    let mut queue = Supervisor::with_capacity(1);
    assert_eq!(queue.admit("goal-1"), Admission::Admitted);
    assert_eq!(queue.admit("goal-2"), Admission::Deferred);

    let mut leases = LeaseRegistry::new();
    let lease = leases.acquire("goal-1", "worker-1", 10, 5).unwrap();
    assert_eq!(leases.commit("goal-1", lease.token, 11), Fence::Accepted);

    let mut budgets = BudgetLedger::new(
        Limits::unlimited().with_tokens(5),
        Limits::unlimited().with_tokens(5),
    );
    budgets.charge_tokens("goal-1", 2).unwrap();

    let mut lifecycle = Lifecycle::new();
    lifecycle.admit("goal-1");
    lifecycle.cancel("goal-1", "operator stop").unwrap();
    assert!(!lifecycle.should_execute("goal-1"));

    let reclaimed = reconcile(&mut leases, &lifecycle);
    assert!(reclaimed.reclaimed_goal("goal-1"));

    let tmp = tempfile::tempdir().unwrap();

    let mut worktrees = WorktreeRegistry::new(tmp.path().join("worktrees"));
    worktrees.assign("goal-1").unwrap();
    assert!(worktrees.may_execute("goal-1"));

    let chains = MissionChains::in_workspace(tmp.path());
    chains
        .supervisor()
        .append("supervisor", "digest", true, "ok", "admit goal-1")
        .unwrap();
    chains
        .goal("goal-1")
        .append("child", "digest", true, "ok", "executed goal-1")
        .unwrap();
    let verify = verify_mission(&chains, &["goal-1"]);
    assert!(verify.all_ok());

    let ledger = RunLedger::in_mission(tmp.path());
    ledger.record("goal-1", &RunArtifacts::none_for("local")).unwrap();
    let read = ledger.read();
    assert!(read.is_intact());
    assert_eq!(read.for_goal("goal-1").len(), 1);
}
