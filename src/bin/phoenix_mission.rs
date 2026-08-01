use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use phoenix::budget::{BudgetLedger, Limits};
use phoenix::cloud_backend::{CloudBackend, HttpCloudClient};
use phoenix::execution_backend::{ExecutionBackend, Job, LocalBackend};
use phoenix::hybrid_dag::GoalDag;
use phoenix::lease::{Fence, LeaseRegistry};
use phoenix::lifecycle::Lifecycle;
use phoenix::reconcile::reconcile;
use phoenix::run_artifacts::RunArtifacts;
use phoenix::run_ledger::RunLedger;
use phoenix::supervisor::{Admission, Supervisor};
use phoenix::trace_chains::{verify_mission, MissionChains};
use phoenix::worktrees::WorktreeRegistry;

const GOALS: [&str; 4] = ["a", "b", "c", "d"];

fn build_diamond() -> Result<GoalDag, String> {
    let mut dag = GoalDag::new();
    dag.add_goal("a", &[]).map_err(|err| format!("add a: {err:?}"))?;
    dag.add_goal("b", &["a"]).map_err(|err| format!("add b: {err:?}"))?;
    dag.add_goal("c", &["a"]).map_err(|err| format!("add c: {err:?}"))?;
    dag.add_goal("d", &["b", "c"]).map_err(|err| format!("add d: {err:?}"))?;
    Ok(dag)
}

fn run_mission(backend: &dyn ExecutionBackend, workspace: &Path) -> Result<(), String> {
    let mut dag = build_diamond()?;
    let mut supervisor = Supervisor::with_capacity(1);
    let mut leases = LeaseRegistry::new();
    let mut worktrees = WorktreeRegistry::new(workspace.join("worktrees"));
    let mut budgets = BudgetLedger::new(
        Limits::unlimited().with_tokens(64).with_time(64),
        Limits::unlimited().with_tokens(16).with_time(16),
    );
    let mut lifecycle = Lifecycle::new();
    let chains = MissionChains::in_workspace(workspace);
    let ledger = RunLedger::in_mission(workspace);
    let mut admitted_or_deferred = BTreeSet::new();
    let mut now = 1_u64;

    while !dag.is_settled() {
        let mut runnable_now = Vec::new();

        for goal in dag.ready() {
            if admitted_or_deferred.contains(&goal) {
                continue;
            }
            let verdict = supervisor.admit(&goal);
            match verdict {
                Admission::Admitted => {
                    chains
                        .supervisor()
                        .append("admission", &goal, true, "admitted", "slot free")
                        .map_err(|err| format!("trace append: {err}"))?;
                    admitted_or_deferred.insert(goal.clone());
                    runnable_now.push(goal);
                }
                Admission::Deferred => {
                    chains
                        .supervisor()
                        .append("admission", &goal, true, "deferred", "queued")
                        .map_err(|err| format!("trace append: {err}"))?;
                    admitted_or_deferred.insert(goal);
                }
                Admission::RefusedZeroCapacity => {
                    chains
                        .supervisor()
                        .append("admission", &goal, false, "refused_zero_capacity", "capacity=0")
                        .map_err(|err| format!("trace append: {err}"))?;
                    return Err("supervisor refused admission: zero capacity".to_string());
                }
            }
        }

        while let Some(goal) = supervisor.next_ready() {
            runnable_now.push(goal);
        }

        if runnable_now.is_empty() {
            return Err("mission made no progress".to_string());
        }

        for goal in runnable_now {
            lifecycle.admit(&goal);

            let worktree = worktrees
                .assign_or_existing(&goal)
                .map_err(|err| format!("worktree assignment for {goal}: {err}"))?;
            std::fs::create_dir_all(&worktree)
                .map_err(|err| format!("create worktree for {goal}: {err}"))?;

            budgets
                .charge_tokens(&goal, 1)
                .map_err(|err| format!("token budget for {goal}: {err}"))?;
            budgets
                .charge_time(&goal, 1)
                .map_err(|err| format!("time budget for {goal}: {err}"))?;

            let lease = leases
                .acquire(&goal, backend.name(), now, 10)
                .map_err(|err| format!("lease acquire for {goal}: {err:?}"))?;
            now = now.saturating_add(1);

            let outcome = backend.execute(&Job::new(format!("job-{goal}"), "rustc --version"));
            let committed = matches!(leases.commit(&goal, lease.token, now), Fence::Accepted);
            now = now.saturating_add(1);
            let _ = leases.release(&goal, lease.token);

            let success = committed && outcome.is_completed();
            let signal = if success { "ok" } else { "failed" };
            chains
                .goal(&goal)
                .append("execute", &goal, success, signal, &outcome.detail)
                .map_err(|err| format!("goal trace append for {goal}: {err}"))?;

            let artifacts = if success {
                RunArtifacts::none_for(outcome.backend.clone())
            } else {
                RunArtifacts::none_for(outcome.backend.clone()).with_error(outcome.detail.clone())
            };
            ledger
                .record(&goal, &artifacts)
                .map_err(|err| format!("ledger record for {goal}: {err}"))?;

            if success {
                dag.mark_succeeded(&goal)
                    .map_err(|err| format!("mark_succeeded {goal}: {err:?}"))?;
                lifecycle
                    .complete(&goal)
                    .map_err(|err| format!("lifecycle complete {goal}: {err}"))?;
                chains
                    .supervisor()
                    .append("completion", &goal, true, "completed", "goal completed")
                    .map_err(|err| format!("trace append: {err}"))?;
            } else {
                dag.mark_failed(&goal)
                    .map_err(|err| format!("mark_failed {goal}: {err:?}"))?;
                lifecycle
                    .fail(&goal, outcome.detail)
                    .map_err(|err| format!("lifecycle fail {goal}: {err}"))?;
                chains
                    .supervisor()
                    .append("completion", &goal, false, "failed", "goal failed")
                    .map_err(|err| format!("trace append: {err}"))?;
            }

            supervisor.complete(&goal);
            admitted_or_deferred.remove(&goal);
        }
    }

    let cleanup = reconcile(&mut leases, &lifecycle);
    let verify = verify_mission(&chains, &GOALS);
    let ledger_read = ledger.read();

    println!("mission completed with backend={}", backend.name());
    println!(
        "run ledger entries={} unreadable={} total_cost_micros={}",
        ledger_read.entries.len(),
        ledger_read.unreadable.len(),
        ledger_read.total_cost_micros()
    );
    for entry in &ledger_read.entries {
        println!(
            "ledger goal={} backend={} error={}",
            entry.goal,
            entry.backend,
            entry.error.as_deref().unwrap_or("none")
        );
    }

    println!(
        "supervisor chain_ok={} rows={} broken_at={:?}",
        verify.supervisor.ok, verify.supervisor.rows, verify.supervisor.broken_at
    );
    for chain in &verify.goals {
        println!(
            "goal {} chain_ok={} rows={} broken_at={:?}",
            chain.writer, chain.ok, chain.rows, chain.broken_at
        );
    }
    println!(
        "reconcile reclaimed={} untracked={}",
        cleanup.reclaimed_count(),
        cleanup.untracked.len()
    );

    if !verify.all_ok() {
        return Err(format!(
            "trace verification failed for writers: {:?}",
            verify.broken_writers()
        ));
    }
    Ok(())
}

fn parse_args() -> Result<(String, PathBuf), String> {
    let mut backend = String::from("local");
    let mut workspace = std::env::current_dir().map_err(|err| format!("current dir: {err}"))?;

    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--backend" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--backend requires one of: local|cloud".to_string())?;
                if value != "local" && value != "cloud" {
                    return Err(format!("unsupported backend {value:?}; expected local|cloud"));
                }
                backend = value;
            }
            "--workspace" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--workspace requires a directory path".to_string())?;
                workspace = PathBuf::from(value);
            }
            "--help" | "-h" => {
                return Err(
                    "usage: phoenix_mission [--backend local|cloud] [--workspace PATH]".to_string(),
                );
            }
            other => return Err(format!("unknown argument {other:?}")),
        }
    }

    Ok((backend, workspace))
}

fn main() -> ExitCode {
    let (backend, workspace) = match parse_args() {
        Ok(parsed) => parsed,
        Err(msg) => {
            eprintln!("{msg}");
            return ExitCode::from(2);
        }
    };

    let result = if backend == "cloud" {
        match HttpCloudClient::from_env() {
            Ok(client) => run_mission(&CloudBackend::new(client), &workspace),
            Err(err) => Err(format!("cloud backend setup failed: {err}")),
        }
    } else {
        run_mission(&LocalBackend, &workspace)
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("mission failed: {err}");
            ExitCode::FAILURE
        }
    }
}
