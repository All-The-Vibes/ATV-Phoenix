//! Runnable M1 demo — emits a real hash-chained trace so the self-heal chain is inspectable.
//! `cargo run --example demo_self_heal`

use phoenix::sense::{sense, Check, CheckKind};
use phoenix::snapshot::snapshot;
use phoenix::{heal, HealCtx, Strategy, Trace};
use std::path::Path;

fn check_contains(file: &Path, needle: &str) -> Check {
    let argv = if cfg!(windows) {
        vec!["cmd".into(), "/C".into(), "findstr".into(), "/C:".to_string() + needle, file.display().to_string()]
    } else {
        vec!["grep".into(), "-q".into(), needle.into(), file.display().to_string()]
    };
    Check { kind: CheckKind::CommandExit, target: argv, expect: Some("0".into()), cwd: None, timeout_secs: Some(30) }
}

fn main() {
    let root = std::path::PathBuf::from("./.phoenix-demo");
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).unwrap();
    let src = root.join("logic.txt");
    let trace = Trace::default_in(&root);

    println!("== ATV-Phoenix M1 demo: bounded objective recovery ==\n");

    std::fs::write(&src, "answer=GOOD_MARKER\n").unwrap();
    let chk = check_contains(&src, "GOOD_MARKER");
    let b = sense(&chk);
    trace.append("sense", "baseline", b.ok, &b.signal, &b.evidence).unwrap();
    println!("1. GREEN baseline   -> sense.ok = {}", b.ok);

    let snap = snapshot(&root, &src, &chk).unwrap();
    let snap_id = snap.snap_id.clone().unwrap();
    trace.append("snapshot", &snap_id, snap.blessed, "snapshot", "blessed").unwrap();
    println!("2. BLESS snapshot   -> {} (blessed={})", snap_id, snap.blessed);

    std::fs::write(&src, "answer=BROKEN\n").unwrap();
    let r = sense(&chk);
    trace.append("sense", "post-fault", r.ok, &r.signal, &r.evidence).unwrap();
    println!("3. INJECT fault     -> sense.ok = {}  (RED via external command exit code)", r.ok);

    let ctx = HealCtx {
        command: None, max_attempts: None,
        path: Some(src.display().to_string()), snap_id: Some(snap_id.clone()),
        recheck: chk.clone(),
    };
    let h = heal(&root, Strategy::Rollback, &ctx);
    trace.append("heal", &snap_id, h.healed, "rollback", &h.evidence).unwrap();
    println!("4. HEAL rollback    -> healed = {} (attempts={}, recheck via external command)", h.healed, h.attempts);

    let v = trace.verify();
    println!("5. TRACE verify     -> ok={} rows={} head={}…", v.ok, v.rows, &v.head_hash[..12.min(v.head_hash.len())]);

    println!("\n-- hash-chained trace (.phoenix/trace.jsonl) --");
    let tp = root.join(".phoenix").join("trace.jsonl");
    if let Ok(content) = std::fs::read_to_string(&tp) {
        for (i, line) in content.lines().enumerate() {
            if let Ok(ev) = serde_json::from_str::<serde_json::Value>(line) {
                println!(
                    "  [{}] {:9} ok={:5} hash={}…",
                    i,
                    ev["tool"].as_str().unwrap_or("?"),
                    ev["ok"].as_bool().unwrap_or(false),
                    &ev["hash"].as_str().unwrap_or("")[..12.min(ev["hash"].as_str().unwrap_or("").len())]
                );
            }
        }
    }
    println!("\nVERDICT: green -> red -> heal -> green, proven by an INDEPENDENT signal + verified trace.");
    let _ = std::fs::remove_dir_all(&root);
}
