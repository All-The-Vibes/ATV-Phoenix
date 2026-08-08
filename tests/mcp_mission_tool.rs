//! Proves the supervisor mission runtime is REACHABLE from the MCP surface.
//!
//! The runtime (supervisor, worktrees, leases, budgets, DAG, run ledger, per-goal trace chains,
//! cloud dispatch) was merged and compiled, but no MCP tool and no skill referenced it — so no
//! agent could ever invoke it. Compiled-and-unreachable is indistinguishable from absent at the
//! only boundary that matters: the one the agent calls through.
//!
//! This is the failure-first gate for that seam. It drives the real phoenix-mcp binary over MCP
//! stdio JSON-RPC exactly as Copilot would, and fails when `phoenix_mission` is missing from
//! `tools/list` or cannot run a dependency-ordered DAG end to end.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{channel, Receiver, RecvTimeoutError};
use std::time::Duration;

/// A reply must arrive within this window. A gate that hangs is not a gate — it never reports.
const REPLY_TIMEOUT: Duration = Duration::from_secs(180);

struct Server {
    child: Child,
    stdin: ChildStdin,
    rx: Receiver<String>,
}

impl Server {
    fn start(workspace: &std::path::Path) -> Self {
        let bin = env!("CARGO_BIN_EXE_phoenix-mcp");
        let mut child = Command::new(bin)
            .env("PHOENIX_WORKSPACE", workspace)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn phoenix-mcp");
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();

        // Drain stdout on a side thread so a missing reply becomes a timeout, not a deadlock.
        let (tx, rx) = channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if tx.send(line).is_err() {
                    return;
                }
            }
        });

        Server { child, stdin, rx }
    }

    fn send(&mut self, line: &str) {
        self.stdin.write_all(line.as_bytes()).unwrap();
        self.stdin.write_all(b"\n").unwrap();
        self.stdin.flush().unwrap();
    }

    fn read_id(&mut self, id: u64) -> serde_json::Value {
        loop {
            match self.rx.recv_timeout(REPLY_TIMEOUT) {
                Ok(line) => {
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(line.trim()) {
                        if v.get("id").and_then(|i| i.as_u64()) == Some(id) {
                            return v;
                        }
                    }
                }
                Err(RecvTimeoutError::Timeout) => {
                    panic!("no response for id={id} within {REPLY_TIMEOUT:?}")
                }
                Err(RecvTimeoutError::Disconnected) => {
                    panic!("server closed stdout before responding to id={id}")
                }
            }
        }
    }

    fn handshake(&mut self) {
        self.send(r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"copilot-like","version":"1"}}}"#);
        self.read_id(1);
        self.send(r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#);
    }

    /// Call a tool with `args`, serialized compactly.
    ///
    /// The stdio transport is newline-delimited JSON, so a request MUST occupy exactly one line.
    /// Building it through `serde_json` (instead of interpolating a pretty-printed literal) makes
    /// that structural, and drops the hand-escaped `{{`/`}}` in format strings at the same time.
    fn call(&mut self, id: u64, tool: &str, args: serde_json::Value) -> serde_json::Value {
        let req = serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": "tools/call",
            "params": { "name": tool, "arguments": args },
        });
        let line = serde_json::to_string(&req).expect("request serializes");
        assert!(!line.contains('\n'), "a request must be exactly one line");
        self.send(&line);
        self.read_id(id)
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn tool_json(resp: &serde_json::Value) -> serde_json::Value {
    let text = resp["result"]["content"][0]["text"].as_str().unwrap_or("{}");
    serde_json::from_str(text).unwrap_or(serde_json::json!({}))
}

/// A diamond DAG: `a` fans out to `b` and `c`, which both gate `d`.
///
/// Every task is a rustc/cargo subcommand, so it exists wherever `cargo test` runs and the
/// assertions below turn on scheduling behaviour rather than on tool availability.
/// Goals are deliberately declared out of dependency order to prove the planner sorts them.
fn diamond_mission() -> serde_json::Value {
    serde_json::json!({
        "capacity": 2,
        "backend": "local",
        "goals": [
            {"id":"d","depends_on":["b","c"], "task":"rustc --print target-libdir"},
            {"id":"b","depends_on":["a"],     "task":"cargo --version"},
            {"id":"c","depends_on":["a"],     "task":"rustc --print sysroot"},
            {"id":"a","depends_on":[],        "task":"rustc --version"}
        ]
    })
}

#[test]
fn mission_tool_is_listed_on_the_mcp_surface() {
    let ws = tempfile::tempdir().unwrap();
    let mut s = Server::start(ws.path());
    s.handshake();

    s.send(r#"{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}"#);
    let listed = s.read_id(2);    let tools = listed["result"]["tools"]
        .as_array()
        .expect("tools/list must return a tools array");
    let names: Vec<&str> = tools.iter().filter_map(|t| t["name"].as_str()).collect();

    assert!(
        names.contains(&"phoenix_mission"),
        "the supervisor runtime is compiled but unreachable: phoenix_mission is absent from the \
         MCP surface. Exposed tools = {names:?}"
    );
}

#[test]
fn mission_tool_runs_a_dependency_ordered_dag_with_isolation() {
    let ws = tempfile::tempdir().unwrap();
    let mut s = Server::start(ws.path());
    s.handshake();

    let m = tool_json(&s.call(2, "phoenix_mission", diamond_mission()));
    assert_eq!(m["ok"], true, "mission must succeed: {m}");
    assert_eq!(m["settled"], true, "every goal must reach a terminal state: {m}");
    assert_eq!(m["backend"], "local", "backend must be echoed: {m}");

    assert_eq!(m["goals_total"], 4, "all four goals must be in the graph: {m}");
    assert_eq!(m["goals_succeeded"], 4, "all four goals must succeed: {m}");
    assert_eq!(m["goals_failed"], 0, "no goal may fail: {m}");

    // Bounded admission: the supervisor must never admit more than `capacity` at once.
    let peak = m["peak_concurrency"].as_u64().expect("peak_concurrency");
    assert!(peak >= 1 && peak <= 2, "peak concurrency must respect capacity=2, got {peak}: {m}");

    // Isolation is the reason worktrees + leases exist; assert it held at execution time.
    assert_eq!(m["isolation_ok"], true, "every executed goal must hold a lease AND a worktree: {m}");

    // Per-goal + supervisor trace chains must independently verify.
    assert_eq!(m["chains_ok"], true, "supervisor and goal trace chains must verify: {m}");

    // The durable run ledger is the audit record — one entry per execution.
    assert_eq!(m["ledger"]["entries"], 4, "run ledger must hold one entry per goal: {m}");
    assert_eq!(m["ledger"]["unreadable"], 0, "no ledger entry may be unreadable: {m}");

    // Dependency order: `a` before `b`/`c`, and `d` last.
    let order: Vec<&str> =
        m["goals"].as_array().expect("goals array").iter().filter_map(|g| g["goal"].as_str()).collect();
    assert_eq!(order.first(), Some(&"a"), "the root goal must run first: {order:?}");
    assert_eq!(order.last(), Some(&"d"), "the join goal must run last: {order:?}");
    assert_eq!(order.len(), 4, "each goal runs exactly once: {order:?}");
}

#[test]
fn mission_tool_reports_a_cycle_instead_of_panicking() {
    let ws = tempfile::tempdir().unwrap();
    let mut s = Server::start(ws.path());
    s.handshake();

    // `x` and `y` require each other: no goal is ever ready.
    let cyclic = serde_json::json!({
        "capacity": 2,
        "goals": [
            {"id":"x","depends_on":["y"],"task":"rustc --version"},
            {"id":"y","depends_on":["x"],"task":"rustc --version"}
        ]
    });
    let m = tool_json(&s.call(2, "phoenix_mission", cyclic));

    assert_eq!(m["ok"], false, "a cyclic DAG must be refused, not run: {m}");
    assert!(
        m["error"].as_str().unwrap_or_default().to_lowercase().contains("cycle")
            || m["reason"].as_str().unwrap_or_default().to_lowercase().contains("cycle"),
        "the refusal must name the cycle so the caller can fix the DAG: {m}"
    );
}
