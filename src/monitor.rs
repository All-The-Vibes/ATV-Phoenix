//! phoenix monitor -- CLI-mode snapshot of a phoenix-ralph run state.
//!
//! Reads .phoenix-ralph/{backlog.json,done-check.json,driver.log,completed.json}
//! and .phoenix/trace.jsonl from the workspace (or --dir override), prints a concise
//! status snapshot, and exits 0. Read-only: never writes anything.
use std::path::Path;
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Serialize, Default)]
pub struct MonitorSnapshot {
    pub state_dir: String,
    pub is_complete: bool,
    pub loop_current: Option<u32>,
    pub loop_max: Option<u32>,
    pub no_progress: Option<u32>,
    pub backlog_total: u32,
    pub backlog_done: u32,
    pub current_item: Option<String>,
    pub trace_events: u32,
    pub trace_intact: Option<bool>,
    pub last_sense_ok: Option<bool>,
    pub last_sense_signal: Option<String>,
    pub accept_ok: Option<bool>,
    pub accept_saw_red: Option<bool>,
    pub accept_green_after_red: Option<bool>,
    pub accept_trace_intact: Option<bool>,
}

fn read_json_file(path: &Path) -> Option<Value> {
    let raw = std::fs::read(path).ok()?;
    // strip UTF-8 BOM if present
    let bytes = if raw.starts_with(b"\xef\xbb\xbf") { &raw[3..] } else { &raw[..] };
    serde_json::from_slice(bytes).ok()
}

fn count_lines(path: &Path) -> u32 {
    std::fs::read_to_string(path)
        .map(|s| s.lines().filter(|l| !l.trim().is_empty()).count() as u32)
        .unwrap_or(0)
}

fn parse_driver_log(log_path: &Path) -> (Option<u32>, Option<u32>, Option<u32>) {
    let content = match std::fs::read_to_string(log_path) {
        Ok(c) => c,
        Err(_) => return (None, None, None),
    };
    let mut loop_cur = None;
    let mut loop_max = None;
    let mut no_prog = None;
    for line in content.lines() {
        // "[ralph] iteration N/M"
        if let Some(rest) = line.find("iteration ").map(|i| &line[i + "iteration ".len()..]) {
            let parts: Vec<&str> = rest.splitn(2, '/').collect();
            if parts.len() == 2 {
                loop_cur = parts[0].trim().parse().ok();
                loop_max = parts[1].split_whitespace().next().and_then(|s| s.parse().ok());
            }
        }
        // "[ralph] no state change (N/M)"
        if let Some(rest) = line.find("no state change (").map(|i| &line[i + "no state change (".len()..]) {
            no_prog = rest.split('/').next().and_then(|s| s.trim().parse().ok());
        }
    }
    (loop_cur, loop_max, no_prog)
}

pub fn snapshot(workspace: &Path, state_dir_rel: &str, phoenix_bin: &Path) -> MonitorSnapshot {
    let state = workspace.join(state_dir_rel);
    let trace_path = workspace.join(".phoenix").join("trace.jsonl");

    let backlog = read_json_file(&state.join("backlog.json"));
    let completed = state.join("completed.json");
    let driver_log = state.join("driver.log");

    let is_complete = completed.exists();
    let (loop_cur, loop_max, no_prog) = parse_driver_log(&driver_log);

    // backlog stats
    let (backlog_total, backlog_done, current_item) = match &backlog {
        Some(Value::Array(items)) => {
            let total = items.len() as u32;
            let done = items.iter().filter(|i| i.get("done").and_then(Value::as_bool).unwrap_or(false)).count() as u32;
            let cur = items.iter()
                .find(|i| !i.get("done").and_then(Value::as_bool).unwrap_or(false))
                .and_then(|i| i.get("title").and_then(Value::as_str))
                .map(|s| s.to_string());
            (total, done, cur)
        }
        _ => (0, 0, None),
    };

    let trace_events = count_lines(&trace_path);

    // verify-trace via binary
    let trace_intact = std::process::Command::new(phoenix_bin)
        .arg("verify-trace")
        .current_dir(workspace)
        .env("PHOENIX_WORKSPACE", workspace)
        .output()
        .ok()
        .map(|o| o.status.success());

    // last sense from trace
    let (last_sense_ok, last_sense_signal) = std::fs::read_to_string(&trace_path)
        .ok()
        .and_then(|s| s.lines().filter(|l| !l.trim().is_empty()).last().map(|l| l.to_string()))
        .and_then(|line| serde_json::from_str::<Value>(&line).ok())
        .map(|v| {
            let ok = v.get("ok").and_then(Value::as_bool);
            let sig = v.get("signal").and_then(Value::as_str).map(|s| s.to_string());
            (ok, sig)
        })
        .unwrap_or((None, None));

    // accept verdict via done-check.json
    let done_check_path = state.join("done-check.json");
    let (accept_ok, accept_saw_red, accept_green_after, accept_ti) = if done_check_path.exists() {
        let tmp = std::env::temp_dir().join(format!("phoenix-monitor-check-{}.json", std::process::id()));
        if std::fs::copy(&done_check_path, &tmp).is_ok() {
            let arg = format!("@{}", tmp.display());
            let out = std::process::Command::new(phoenix_bin)
                .args(["accept", &arg])
                .current_dir(workspace)
                .env("PHOENIX_WORKSPACE", workspace)
                .output()
                .ok();
            let _ = std::fs::remove_file(&tmp);
            out.and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok())
                .map(|v| {
                    let ok   = v.get("ok").and_then(Value::as_bool);
                    let sr   = v.get("saw_red").and_then(Value::as_bool);
                    let ga   = v.get("green_after_red").and_then(Value::as_bool);
                    let ti   = v.get("trace_intact").and_then(Value::as_bool);
                    (ok, sr, ga, ti)
                })
                .unwrap_or((None, None, None, None))
        } else { (None, None, None, None) }
    } else { (None, None, None, None) };

    MonitorSnapshot {
        state_dir: state.display().to_string(),
        is_complete,
        loop_current: loop_cur,
        loop_max,
        no_progress: no_prog,
        backlog_total,
        backlog_done,
        current_item,
        trace_events,
        trace_intact,
        last_sense_ok,
        last_sense_signal,
        accept_ok,
        accept_saw_red,
        accept_green_after_red: accept_green_after,
        accept_trace_intact: accept_ti,
    }
}

pub fn print_snapshot(s: &MonitorSnapshot) {
    let state_str = if s.is_complete { "COMPLETE" } else if s.loop_current.is_some() { "RUNNING" } else { "IDLE" };
    let loop_str = match (s.loop_current, s.loop_max) {
        (Some(c), Some(m)) => format!("{c}/{m}"),
        _ => "--".to_string(),
    };
    let np_str = s.no_progress.map(|n| n.to_string()).unwrap_or_else(|| "--".to_string());
    let bl_str = format!("{}/{}", s.backlog_done, s.backlog_total);
    let cur_str = s.current_item.as_deref().unwrap_or("(none)");
    let ti_str = match s.trace_intact { Some(true) => "INTACT", Some(false) => "BROKEN", None => "--" };
    let ls_str = match s.last_sense_ok { Some(true) => "GREEN", Some(false) => "RED", None => "--" };
    let ls_sig = s.last_sense_signal.as_deref().unwrap_or("");
    let ac_str = match s.accept_ok { Some(true) => "PROVEN", Some(false) => "UNPROVEN", None => "--" };
    let ac_saw = s.accept_saw_red.map(|b| format!("saw_red={b}")).unwrap_or_default();

    println!("phoenix-ralph monitor  state={state_str}");
    println!("  loop        {loop_str}");
    println!("  no-progress {np_str}");
    println!("  backlog     {bl_str}  current: {cur_str}");
    println!("  trace       {} events  chain={ti_str}", s.trace_events);
    println!("  last sense  {ls_str}  {ls_sig}");
    println!("  done-check  {ac_str}  {ac_saw}");
}