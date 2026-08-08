//! Does the concurrency that landed in #176 buy wall-clock on real work? (issue #177)
//!
//! Every prior concurrency test used a backend that sleeps. A sleeping backend proves the
//! scheduler overlaps, which is necessary and not sufficient: sleeps are perfectly parallel by
//! construction, so they cannot expose a real workload's contention for CPU, disk, or a process
//! table. This test dispatches 10 ARC-AGI-3 environments as 10 independent goals through the same
//! `MissionPlan::run` the `phoenix_mission` tool calls, at capacity 1 and then at capacity 10.
//!
//! The DAG is deliberately flat. Module docs on `mission` say the ceiling is DAG shape rather than
//! `capacity`, and 183 independent levels across 25 environments is the first workload in this
//! repository whose shape can actually cash that in.
//!
//! Ignored by default: it spawns real Python processes and takes roughly a minute. Run it with
//!   cargo test --test arc_mission_concurrency -- --ignored --nocapture

use std::time::{Duration, Instant};

use phoenix::execution_backend::LocalBackend;
use phoenix::mission::MissionConfig;
use phoenix::mission_plan::{plan, GoalSpec};

/// Ten environments. `sp80` and `cd82` are the two a model-free policy has been observed to score
/// on, so the batch is not uniformly zero and a regression in dispatch would show up as lost
/// levels rather than only as lost time.
const GAMES: [&str; 10] =
    ["sp80", "cd82", "ls20", "ft09", "tn36", "vc33", "r11l", "sb26", "lp85", "su15"];

const BUDGET: &str = "1500";

fn goals() -> Vec<GoalSpec> {
    GAMES
        .iter()
        .map(|g| {
            GoalSpec::new(
                format!("arc-{g}"),
                Vec::<String>::new(),
                format!(
                    "python -m evals.arc.run_arc --policy novelty --games {g} --budget {BUDGET}"
                ),
            )
        })
        .collect()
}

fn run_at(capacity: usize, tag: &str) -> (Duration, usize, usize) {
    let planned = plan(goals()).expect("flat DAG of unique ids must plan");
    let workspace = std::env::temp_dir().join(format!("arc-mission-{tag}-{capacity}"));
    let _ = std::fs::remove_dir_all(&workspace);

    let backend = LocalBackend;
    let started = Instant::now();
    let report = planned.run(MissionConfig::new(capacity), &workspace, &backend);
    let elapsed = started.elapsed();

    assert!(report.settled, "capacity {capacity}: mission did not settle");
    assert!(
        report.chain_verify.all_ok(),
        "capacity {capacity}: trace chains did not verify"
    );
    assert!(
        report.all_executed_held_lease_and_worktree(),
        "capacity {capacity}: a goal executed without both a lease and a worktree"
    );

    let executed = report.executed_goals().count();
    (elapsed, executed, report.peak_concurrency)
}

#[test]
#[ignore = "spawns 20 real Python processes; run explicitly with --ignored"]
fn concurrent_dispatch_beats_serial_on_real_arc_work() {
    let (serial, serial_n, serial_peak) = run_at(1, "serial");
    let (concurrent, conc_n, conc_peak) = run_at(GAMES.len(), "concurrent");

    println!("serial     capacity=1  elapsed={serial:?} executed={serial_n} peak={serial_peak}");
    println!("concurrent capacity={}  elapsed={concurrent:?} executed={conc_n} peak={conc_peak}",
        GAMES.len());
    println!(
        "speedup    {:.2}x",
        serial.as_secs_f64() / concurrent.as_secs_f64()
    );

    assert_eq!(serial_n, GAMES.len(), "serial run lost goals");
    assert_eq!(conc_n, GAMES.len(), "concurrent run lost goals");

    // Capacity 1 must never overlap. This is the control: if it does, the two arms are not
    // measuring different things and the speedup below means nothing.
    assert_eq!(serial_peak, 1, "capacity 1 admitted more than one goal at a time");
    assert!(conc_peak > 1, "capacity {} never admitted concurrently", GAMES.len());

    // A deliberately loose bar. The claim under test is that real overlap happens at all, not that
    // it scales linearly: 10 Python interpreters contend for CPU and each pays interpreter startup,
    // so perfect scaling is not available and asserting it would make this test flaky by design.
    assert!(
        concurrent < serial,
        "concurrent ({concurrent:?}) was not faster than serial ({serial:?})"
    );
}
