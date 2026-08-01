use std::path::{Path, PathBuf};
use std::process::ExitCode;

use phoenix::cloud_backend::{CloudBackend, HttpCloudClient};
use phoenix::execution_backend::{ExecutionBackend, Job, LocalBackend};
use phoenix::mission::{MissionConfig, run_mission};
use phoenix::run_ledger::RunLedger;

const GOALS: [(&str, &[&str]); 4] = [
    ("a", &[]),
    ("b", &["a"]),
    ("c", &["a"]),
    ("d", &["b", "c"]),
];
const MISSION_TASK: &str = "rustc --version";

struct FixedTaskBackend<'a> {
    inner: &'a dyn ExecutionBackend,
    task: &'a str,
}

impl ExecutionBackend for FixedTaskBackend<'_> {
    fn name(&self) -> &str {
        self.inner.name()
    }

    fn preflight(&self, job: &Job) -> phoenix::execution_backend::PreflightOutcome {
        let mapped = Job::new(job.id.clone(), self.task);
        self.inner.preflight(&mapped)
    }

    fn execute(&self, job: &Job) -> phoenix::execution_backend::BackendOutcome {
        let mapped = Job::new(job.id.clone(), self.task);
        self.inner.execute(&mapped)
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

fn run_with_backend(backend: &dyn ExecutionBackend, workspace: &Path) -> Result<(), String> {
    let mission_backend = FixedTaskBackend { inner: backend, task: MISSION_TASK };
    let report = run_mission(&GOALS, MissionConfig::new(2), workspace, &mission_backend);

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
