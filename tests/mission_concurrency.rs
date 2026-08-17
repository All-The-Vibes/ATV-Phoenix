//! Proves the mission runner executes independent goals **concurrently**, not merely unordered.
//!
//! Done-check: `cargo test --locked --test mission_concurrency`
//!
//! `capacity` used to bound admission only — the scheduler ran one `backend.execute` at a time, so
//! raising it changed nothing a caller could measure. `peak_concurrency` reported admission depth,
//! which made the report look concurrent while wall-clock time stayed serial. That gap is exactly
//! the kind a summary field hides, so these tests observe overlap from *inside* the backend rather
//! than trusting the number the runner reports.
//!
//! Two independent observations:
//!
//! 1. **Structural** — a barrier that only releases once N goals are inside `execute` at the same
//!    time. If execution were serial the barrier could never trip and the test would time out
//!    rather than quietly pass.
//! 2. **Occupancy under ordinary work** — N goals sleeping a fixed duration are inside
//!    `execute` at the same instant, with a paired capacity-1 run proving the same measurement
//!    reads 1 when execution is serialized.
//!
//! Both are needed: the barrier proves goals can be made to meet, and the sleeping run proves
//! ordinary work overlaps without being forced to. Neither reads a clock, because issue #214
//! showed a wall-clock ceiling fails on a loaded machine that is executing concurrently.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use phoenix::execution_backend::{BackendOutcome, ExecutionBackend, Job, PreflightOutcome};
use phoenix::mission::{run_mission, MissionConfig};
use tempfile::TempDir;

/// How long a goal waits for its peers before giving up. Only reached when execution is serial,
/// so it costs nothing on the passing path and bounds the failing one.
const RENDEZVOUS_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Default)]
struct Rendezvous {
    /// Goals that have arrived in the current round.
    arrived: usize,
    /// Bumped each time a round completes, so a waiter can tell "my round finished" from
    /// "the counter happens to look low again because peers already left".
    generation: u64,
}

/// Holds every job inside `execute` until `expect` of them have arrived.
///
/// A plain `Barrier` would deadlock forever under a serial scheduler — a gate that hangs never
/// reports. This uses a `Condvar` with a timeout instead, so serial execution produces a clean
/// failed assertion (`high_water == 1`) rather than a stuck run.
///
/// The round is generation-based on purpose. Keying the wait on the arrival count alone is racy:
/// the final arriver releases the round and departs, dropping the count below `expect` before a
/// waiter re-checks, which strands that waiter until its timeout.
struct RendezvousBackend {
    expect: usize,
    round: Mutex<Rendezvous>,
    released: Condvar,
    /// True simultaneous occupancy: incremented on entry, decremented on exit.
    inside: AtomicUsize,
    high_water: Arc<AtomicUsize>,
}

impl RendezvousBackend {
    fn new(expect: usize, high_water: Arc<AtomicUsize>) -> Self {
        Self {
            expect,
            round: Mutex::new(Rendezvous::default()),
            released: Condvar::new(),
            inside: AtomicUsize::new(0),
            high_water,
        }
    }
}

impl ExecutionBackend for RendezvousBackend {
    fn name(&self) -> &str {
        "rendezvous"
    }

    fn preflight(&self, _job: &Job) -> PreflightOutcome {
        PreflightOutcome::eligible()
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        let occupancy = self.inside.fetch_add(1, Ordering::SeqCst) + 1;
        self.high_water.fetch_max(occupancy, Ordering::SeqCst);

        {
            let mut round = self.round.lock().unwrap();
            let my_generation = round.generation;
            round.arrived += 1;

            if round.arrived >= self.expect {
                // Final arriver closes the round and releases every waiter.
                round.arrived = 0;
                round.generation += 1;
                self.released.notify_all();
            } else {
                let deadline = Instant::now() + RENDEZVOUS_TIMEOUT;
                while round.generation == my_generation {
                    let remaining = deadline.saturating_duration_since(Instant::now());
                    if remaining.is_zero() {
                        break;
                    }
                    let (guard, _) = self.released.wait_timeout(round, remaining).unwrap();
                    round = guard;
                }
            }
        }

        self.inside.fetch_sub(1, Ordering::SeqCst);
        BackendOutcome::completed(&job.id, "rendezvous", "ok")
    }
}

/// Sleeps a fixed duration per job and records true simultaneous occupancy while it does.
///
/// The sleep is ordinary work holding a slot rather than a barrier that forces the answer, so
/// the high-water mark measures overlap the scheduler produced on its own. Measured together
/// with the clock on this runner: 4 jobs of 300ms, elapsed 400.5ms, peak occupancy 4.
struct SleepBackend {
    per_job: Duration,
    /// Live occupancy: incremented on entry to `execute`, decremented on exit.
    inside: AtomicUsize,
    high_water: Arc<AtomicUsize>,
}

impl SleepBackend {
    fn new(per_job: Duration, high_water: Arc<AtomicUsize>) -> Self {
        Self { per_job, inside: AtomicUsize::new(0), high_water }
    }
}

impl ExecutionBackend for SleepBackend {
    fn name(&self) -> &str {
        "sleep"
    }

    fn preflight(&self, _job: &Job) -> PreflightOutcome {
        PreflightOutcome::eligible()
    }

    fn execute(&self, job: &Job) -> BackendOutcome {
        let occupancy = self.inside.fetch_add(1, Ordering::SeqCst) + 1;
        self.high_water.fetch_max(occupancy, Ordering::SeqCst);
        std::thread::sleep(self.per_job);
        self.inside.fetch_sub(1, Ordering::SeqCst);
        BackendOutcome::completed(&job.id, "sleep", "ok")
    }
}

#[test]
fn four_independent_goals_are_inside_execute_at_the_same_time() {
    let ws = TempDir::new().unwrap();
    let goals: &[(&str, &[&str])] = &[("a", &[]), ("b", &[]), ("c", &[]), ("d", &[])];

    let high_water = Arc::new(AtomicUsize::new(0));
    // 4 participants: the rendezvous only trips if all four goals are in execute together.
    let backend = RendezvousBackend::new(4, Arc::clone(&high_water));

    let report = run_mission(goals, MissionConfig::new(4), ws.path(), &backend);

    assert!(report.settled, "mission must settle");
    assert_eq!(
        high_water.load(Ordering::SeqCst),
        4,
        "four goals must be inside execute simultaneously; capacity is a real parallelism limit, \
         not just an admission counter"
    );
    assert_eq!(report.records.len(), 4, "every goal must be recorded");
    assert!(
        report.all_executed_held_lease_and_worktree(),
        "isolation must still hold when goals run concurrently"
    );
    assert!(report.chain_verify.all_ok(), "every trace chain must verify after a concurrent run");
}

#[test]
fn capacity_still_caps_true_simultaneous_execution() {
    // Six independent goals, capacity 2: never more than two inside execute at once.
    let ws = TempDir::new().unwrap();
    let goals: &[(&str, &[&str])] =
        &[("a", &[]), ("b", &[]), ("c", &[]), ("d", &[]), ("e", &[]), ("f", &[])];

    let high_water = Arc::new(AtomicUsize::new(0));
    // Batches of 2, so a 2-participant rendezvous trips once per batch.
    let backend = RendezvousBackend::new(2, Arc::clone(&high_water));

    let report = run_mission(goals, MissionConfig::new(2), ws.path(), &backend);

    assert!(report.settled, "mission must settle");
    assert_eq!(
        high_water.load(Ordering::SeqCst),
        2,
        "capacity 2 must permit exactly 2 at once — no more, and no fewer"
    );
    assert!(
        report.peak_concurrency <= 2,
        "reported peak {} exceeded capacity 2",
        report.peak_concurrency
    );
}

/// Run four sleeping goals at `capacity` and report the peak simultaneous occupancy observed.
fn peak_occupancy_of_four_sleeping_goals(capacity: usize) -> usize {
    let ws = TempDir::new().unwrap();
    let goals: &[(&str, &[&str])] = &[("a", &[]), ("b", &[]), ("c", &[]), ("d", &[])];

    let high_water = Arc::new(AtomicUsize::new(0));
    let backend = SleepBackend::new(Duration::from_millis(300), Arc::clone(&high_water));

    let report = run_mission(goals, MissionConfig::new(capacity), ws.path(), &backend);

    assert!(report.settled, "mission must settle");
    high_water.load(Ordering::SeqCst)
}

#[test]
fn concurrent_execution_overlaps_real_work_rather_than_serializing() {
    // Issue #214. This was a wall-clock ceiling: 4 jobs of 300ms had to finish under 900ms.
    // Serial is 1200ms, so a loaded machine at 949ms was genuinely concurrent and still failed.
    // That costs more than an ordinary flake, because `cargo test` halts on the first failing
    // binary: one trip here left 17 of 49 binaries unrun, and counting `test result:` lines read
    // 171 passing instead of 294, which looks like a smaller green suite.
    //
    // Occupancy is the property the word concurrent names, and it does not move with load. A
    // busy box slows the spawn and the sleep together, so four jobs sleeping 300ms are still
    // inside `execute` at the same instant. Measured on this runner in one run: elapsed
    // 400.5ms, peak occupancy 4.
    assert_eq!(
        peak_occupancy_of_four_sleeping_goals(4),
        4,
        "four sleeping goals must be inside execute at the same instant at capacity 4"
    );
}

#[test]
fn the_overlap_observation_reads_one_when_execution_is_serialized() {
    // The negative control, shipped rather than run once and described. A detector that cannot
    // report serial execution proves nothing about the case above, and the assertion this
    // replaces had no such companion. Capacity 1 is genuine serialization and the same
    // measurement must say so.
    assert_eq!(
        peak_occupancy_of_four_sleeping_goals(1),
        1,
        "capacity 1 is serial; the occupancy observation must be able to say so"
    );
}

#[test]
fn a_panicking_backend_fails_its_goal_without_killing_the_mission() {
    // The runner is hosted inside a long-lived MCP server, so one bad job must not unwind the
    // scheduler and take every other Phoenix tool down with it.
    struct PanicsOnce {
        victim: String,
        seen: Mutex<Vec<String>>,
    }

    impl ExecutionBackend for PanicsOnce {
        fn name(&self) -> &str {
            "panics-once"
        }
        fn preflight(&self, _job: &Job) -> PreflightOutcome {
            PreflightOutcome::eligible()
        }
        fn execute(&self, job: &Job) -> BackendOutcome {
            self.seen.lock().unwrap().push(job.id.clone());
            if job.id == self.victim {
                panic!("injected backend panic for {}", job.id);
            }
            BackendOutcome::completed(&job.id, "panics-once", "ok")
        }
    }

    let ws = TempDir::new().unwrap();
    let goals: &[(&str, &[&str])] = &[("a", &[]), ("b", &[]), ("c", &[])];
    let backend = PanicsOnce { victim: "b".to_string(), seen: Mutex::new(Vec::new()) };

    let report = run_mission(goals, MissionConfig::new(3), ws.path(), &backend);

    assert!(report.settled, "the mission must still settle when a backend panics");

    let b = report.records.iter().find(|r| r.goal == "b").expect("b must be recorded");
    assert_eq!(
        b.outcome,
        phoenix::hybrid_dag::GoalOutcome::Failed,
        "the panicking goal must be recorded as failed, not silently dropped"
    );

    for g in ["a", "c"] {
        let rec = report.records.iter().find(|r| r.goal == g).expect("sibling must be recorded");
        assert_eq!(
            rec.outcome,
            phoenix::hybrid_dag::GoalOutcome::Succeeded,
            "{g} must be unaffected by a sibling's panic"
        );
    }
}
