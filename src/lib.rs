//! ATV-Phoenix spine — objective sensing, bounded recovery, blessed snapshots, tamper-evident trace.
//!
//! This is the ONE novel thing Phoenix adds on top of GitHub Copilot + TokenMasterX: the ability to
//! SENSE objective failure and HEAL it within bounded, logged, reversible actions. No LLM here — only
//! objective signals (exit codes, hashes, regex). See docs/v0-spine-design.md.

pub mod accept;
pub mod backend_select;
pub mod budget;
pub mod cloud_backend;
pub mod doctor;
pub mod execution_backend;
pub mod heal;
pub mod hybrid_dag;
pub mod intent;
pub mod lease;
pub mod lifecycle;
pub mod mission;
pub mod monitor;
pub mod prompt_ledger;
pub mod reconcile;
pub mod run_artifacts;
pub mod run_ledger;
pub mod sense;
pub mod snapshot;
pub mod supervisor;
pub mod trace;
pub mod trace_chains;
pub mod worktrees;

pub use accept::{verify_gate, GateResult};
pub use backend_select::{
    select_backend, BackendRejection, RejectionCause, Rejections, Selection, AUTO_BACKEND_NAME,
};
pub use budget::{BudgetExceeded, BudgetLedger, Limits, Resource, Scope, Spend};
pub use cloud_backend::{
    CloudBackend, CloudClient, CloudError, TaskId, TaskReport, TaskState, CLOUD_BACKEND_NAME,
    DEFAULT_MAX_POLLS,
};
pub use doctor::{doctor, fix as doctor_fix, integrity, resolve_home, DoctorReport, InstallReport};
pub use execution_backend::{
    BackendOutcome, BackendStatus, EmptyRefusals, ExecutionBackend, Job, LocalBackend,
    PreflightDimension, PreflightOutcome, PreflightRefusal, Refusals, LOCAL_BACKEND_NAME,
};
pub use heal::{heal, HealCtx, HealResult, Strategy};
pub use hybrid_dag::{
    DagDenied, GoalBackend, GoalDag, GoalDispatch, GoalOutcome, HybridDenied, HybridMission,
    IntegrationFailure, IntegrationWorker, INTEGRATION_WORKTREE,
};
pub use intent::{
    verify_intent, CompositeAcceptResult, GoalAcceptResult, GoalKind, GoalSpec, IntentManifest,
    MAX_GOALS,
};
pub use lease::{Fence, Lease, LeaseDenied, LeaseRegistry, FIRST_TOKEN};
pub use lifecycle::{GoalState, Lifecycle, TransitionDenied};
pub use mission::{ExecutionRecord, MissionError, MissionGoal, MissionReport, MissionRunner};
pub use prompt_ledger::{capture, verify_against, Manifest, Verdict};
pub use reconcile::{reconcile, reconcile_with_audit, ReclaimedLease, Reconciliation};
pub use run_artifacts::{RunArtifacts, Usage};
pub use run_ledger::{LedgerEntry, LedgerRead, RunLedger, LEDGER_FILE};
pub use sense::{sense, Check, CheckKind, SenseResult};
pub use snapshot::{snapshot, SnapshotResult};
pub use supervisor::{Admission, Supervisor};
pub use trace::{Trace, TraceVerify};
pub use trace_chains::{verify_mission, ChainStatus, MissionChains, MissionVerify};
pub use worktrees::{AssignmentDenied, WorktreeRegistry, WORKTREE_PREFIX};
