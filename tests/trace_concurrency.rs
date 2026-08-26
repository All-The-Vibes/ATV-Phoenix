//! Regression coverage for concurrent appenders sharing one trace file.

use std::sync::{Arc, Barrier};

use phoenix::trace::Trace;
use tempfile::TempDir;

#[test]
fn concurrent_appenders_produce_one_intact_chain() {
    const WRITERS: usize = 64;

    let dir = TempDir::new().unwrap();
    let path = dir.path().join("trace.jsonl");
    let barrier = Arc::new(Barrier::new(WRITERS));

    let handles: Vec<_> = (0..WRITERS)
        .map(|writer| {
            let path = path.clone();
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                Trace::at(path)
                    .append(
                        "sense",
                        &format!("digest-{writer}"),
                        true,
                        "command_exit",
                        &format!("writer-{writer}"),
                    )
                    .unwrap();
            })
        })
        .collect();

    for handle in handles {
        handle.join().unwrap();
    }

    let trace = Trace::at(path);
    let verification = trace.verify();
    assert_eq!(
        verification.rows, WRITERS,
        "every append must produce exactly one JSONL row"
    );
    assert!(
        verification.ok,
        "concurrent appenders must serialize into one intact hash chain; break={:?}",
        verification.broken_at
    );
}
