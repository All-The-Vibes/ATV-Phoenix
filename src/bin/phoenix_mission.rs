use std::path::{Path, PathBuf};
use std::process::ExitCode;

use phoenix::cloud_backend::{CloudBackend, HttpCloudClient};
use phoenix::execution_backend::{ExecutionBackend, Job, LocalBackend};
use phoenix::mission::{MissionConfig, run_mission};
use phoenix::run_ledger::RunLedger;

// Each goal carries its own task alongside its prerequisites: (goal_id, prereqs, task).
// The four tasks are genuinely distinct so the diamond DAG runs four different commands, and each
// is a rustc/cargo subcommand that is present wherever `cargo test` runs, so every goal exits 0 and
// the run ledger records four verifiable chains. See issue #141.
const GOALS: [(&str, &[&str], &str); 4] = [
    ("a", &[], "rustc --version"),
    ("b", &["a"], "cargo --version"),
    ("c", &["a"], "rustc --print sysroot"),
    ("d", &["b", "c"], "rustc --print target-libdir"),
];

/// Which backend each goal runs on under `--backend mixed`.
///
/// This is what makes a mission *hybrid* rather than merely capable of two backends: goal `b`
/// executes in the cloud while its siblings execute locally, and `d` depends on one of each. A
/// goal absent from this table falls back to local — stated explicitly so the fallback is a
/// decision rather than an accident. See issue #86.
const MIXED_ROUTES: [(&str, &str); 4] =
    [("a", "local"), ("b", "cloud"), ("c", "local"), ("d", "local")];

/// Attaches each goal its own task, looked up by job id against [`GOALS`], then forwards to `inner`.
///
/// `run_mission` builds every job as `Job::new(goal_id, goal_id)`, so the incoming `job.task` is
/// only the goal id, not real work. This adapter replaces it with the task declared for that id.
/// An id that is not in `GOALS` is forwarded UNCHANGED (its task stays equal to the id) so the
/// mismatch surfaces as a failed job in the ledger rather than being hidden behind a silent default.
/// Handing every goal one constant task was the defect in issue #141.
struct GoalTaskBackend<'a> {
    inner: &'a (dyn ExecutionBackend + Sync),
    goals: &'a [(&'a str, &'a [&'a str], &'a str)],
}

impl<'a> GoalTaskBackend<'a> {
    fn new(
        inner: &'a (dyn ExecutionBackend + Sync),
        goals: &'a [(&'a str, &'a [&'a str], &'a str)],
    ) -> Self {
        Self { inner, goals }
    }

    fn task_for(&self, id: &str) -> Option<&'a str> {
        for &(goal, _, task) in self.goals {
            if goal == id {
                return Some(task);
            }
        }
        None
    }

    fn map_job(&self, job: &Job) -> Job {
        match self.task_for(&job.id) {
            Some(task) => Job::new(job.id.clone(), task),
            None => job.clone(),
        }
    }
}

impl ExecutionBackend for GoalTaskBackend<'_> {
    fn name(&self) -> &str {
        self.inner.name()
    }

    fn preflight(&self, job: &Job) -> phoenix::execution_backend::PreflightOutcome {
        self.inner.preflight(&self.map_job(job))
    }

    fn execute(&self, job: &Job) -> phoenix::execution_backend::BackendOutcome {
        self.inner.execute(&self.map_job(job))
    }
}

/// Routes each job to the backend declared for its goal, so one mission spans both.
///
/// Composes with [`GoalTaskBackend`] rather than duplicating it: the task adapter rewrites the
/// job, then this decides where the rewritten job executes. Keeping the two separate means the
/// routing table cannot silently change what a goal *does*, only where it runs.
///
/// The recorded backend name comes from whichever inner backend actually executed — [`BackendOutcome`]
/// carries its own `backend` field — so the run ledger reports the real destination per goal, not
/// this wrapper's name. That is what makes a mixed mission observable after the fact.
struct RoutingBackend<'a> {
    local: &'a (dyn ExecutionBackend + Sync),
    cloud: &'a (dyn ExecutionBackend + Sync),
    routes: &'a [(&'a str, &'a str)],
}

impl<'a> RoutingBackend<'a> {
    fn new(
        local: &'a (dyn ExecutionBackend + Sync),
        cloud: &'a (dyn ExecutionBackend + Sync),
        routes: &'a [(&'a str, &'a str)],
    ) -> Self {
        Self { local, cloud, routes }
    }

    /// The backend for `id`, defaulting to local for an unrouted goal.
    fn backend_for(&self, id: &str) -> &'a (dyn ExecutionBackend + Sync) {
        for &(goal, target) in self.routes {
            if goal == id && target == "cloud" {
                return self.cloud;
            }
        }
        self.local
    }
}

impl ExecutionBackend for RoutingBackend<'_> {
    fn name(&self) -> &str {
        "mixed"
    }

    fn preflight(&self, job: &Job) -> phoenix::execution_backend::PreflightOutcome {
        self.backend_for(&job.id).preflight(job)
    }

    fn execute(&self, job: &Job) -> phoenix::execution_backend::BackendOutcome {
        self.backend_for(&job.id).execute(job)
    }
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
                    .ok_or_else(|| "--backend requires one of: local|cloud|mixed".to_string())?;
                if value != "local" && value != "cloud" && value != "mixed" {
                    return Err(format!(
                        "unsupported backend {value:?}; expected local|cloud|mixed"
                    ));
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
                    "usage: phoenix_mission [--backend local|cloud|mixed] [--workspace PATH]"
                        .to_string(),
                );
            }
            other => return Err(format!("unknown argument {other:?}")),
        }
    }

    Ok((backend, workspace))
}

fn run_with_backend(backend: &(dyn ExecutionBackend + Sync), workspace: &Path) -> Result<(), String> {
    let mission_backend = GoalTaskBackend::new(backend, &GOALS);
    let dag: Vec<(&str, &[&str])> = GOALS.iter().map(|(goal, prereqs, _)| (*goal, *prereqs)).collect();
    let report = run_mission(&dag, MissionConfig::new(2), workspace, &mission_backend);

    let ledger = RunLedger::at(report.workspace.join("run-ledger.jsonl")).read();

    println!("mission completed with backend={}", backend.name());
    println!(
        "run ledger entries={} unreadable={} total_cost_micros={}",
        ledger.entries.len(),
        ledger.unreadable.len(),
        ledger.total_cost_micros()
    );
    for entry in &ledger.entries {
        println!(
            "ledger goal={} backend={} error={}",
            entry.goal,
            entry.backend,
            entry.error.as_deref().unwrap_or("none")
        );
    }
    println!(
        "supervisor chain_ok={} rows={} broken_at={:?}",
        report.chain_verify.supervisor.ok,
        report.chain_verify.supervisor.rows,
        report.chain_verify.supervisor.broken_at
    );
    for chain in &report.chain_verify.goals {
        println!(
            "goal {} chain_ok={} rows={} broken_at={:?}",
            chain.writer, chain.ok, chain.rows, chain.broken_at
        );
    }

    if !report.chain_verify.all_ok() {
        return Err(format!(
            "trace verification failed for writers: {:?}",
            report.chain_verify.broken_writers()
        ));
    }
    Ok(())
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
            Ok(client) => run_with_backend(&CloudBackend::new(client), &workspace),
            Err(err) => Err(format!("cloud backend setup failed: {err}")),
        }
    } else if backend == "mixed" {
        // A mixed mission still needs a working cloud client: routing a goal to a backend that
        // cannot be constructed would report a local result under a cloud label.
        match HttpCloudClient::from_env() {
            Ok(client) => {
                let cloud = CloudBackend::new(client);
                let routed = RoutingBackend::new(&LocalBackend, &cloud, &MIXED_ROUTES);
                run_with_backend(&routed, &workspace)
            }
            Err(err) => Err(format!("mixed backend setup failed: {err}")),
        }
    } else {
        run_with_backend(&LocalBackend, &workspace)
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("mission failed: {err}");
            ExitCode::FAILURE
        }
    }
}
