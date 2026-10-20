//! A check gets no stdin whether or not it declares `timeout_secs` (#228).
//!
//! `sense_command` starts a check one of two ways. With no deadline it calls `Command::output()`,
//! and std gives the child a null stdin there. With `timeout_secs` it calls `spawn()`, and std's
//! default for `spawn()` is to inherit the parent's stdin. Declaring a deadline therefore changed
//! what the check could read.
//!
//! Under `phoenix-mcp` serving MCP over stdio, the inherited handle is the JSON-RPC channel. The host
//! keeps it open and sends nothing while it waits for the tool result, so a check that reads stdin
//! blocks until the deadline kills it and comes back `ok=false, timed_out=true`. `accept` counts any
//! failed sense row as RED and the trace row does not keep `timed_out`, so that kill reads in the
//! ledger like a check that observed its defect.
//!
//! The fixture is a filter that reads stdin to EOF and exits 0: `cat` on Unix, `sort.exe` on
//! Windows. Given a null stdin it sees EOF at once and passes. Given the server's stdin it waits for
//! input that never comes. The server is the real binary, driven over stdio the way a host drives
//! it, with this test holding its stdin open.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{channel, Receiver};
use std::time::{Duration, Instant};

/// The deadline the check declares. Long enough for a cold process start on a loaded runner. The
/// RED case costs this much wall time, because the blocked fixture is killed at the deadline.
const DEADLINE_SECS: u64 = 10;

/// A filter that reads stdin to EOF and exits 0. Absolute on Windows, so a `sort` from Git or MSYS
/// earlier on PATH cannot stand in for the system one.
fn stdin_filter() -> Vec<String> {
    if cfg!(windows) {
        let root = std::env::var("SystemRoot").unwrap_or_else(|_| r"C:\Windows".to_string());
        vec![format!(r"{root}\System32\sort.exe")]
    } else {
        vec!["cat".to_string()]
    }
}

struct Server {
    child: Child,
    stdin: ChildStdin,
    lines: Receiver<String>,
}

impl Server {
    fn start(workspace: &std::path::Path) -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_phoenix-mcp"))
            .env("PHOENIX_WORKSPACE", workspace)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn phoenix-mcp");
        let stdin = child.stdin.take().expect("server stdin");
        let stdout = child.stdout.take().expect("server stdout");
        // Lines arrive on a channel so every wait below is bounded. A server that never answers
        // fails this test; it does not hang it.
        let (tx, lines) = channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
        Server { child, stdin, lines }
    }

    fn send(&mut self, message: &Value) {
        let mut line = message.to_string();
        line.push('\n');
        self.stdin.write_all(line.as_bytes()).expect("write to server");
        self.stdin.flush().expect("flush server stdin");
    }

    fn response(&self, id: u64) -> Value {
        let limit = Duration::from_secs(DEADLINE_SECS * 6);
        let started = Instant::now();
        loop {
            let left = limit.saturating_sub(started.elapsed());
            let line = self
                .lines
                .recv_timeout(left)
                .unwrap_or_else(|_| panic!("no response to id={id} within {limit:?}"));
            if let Ok(v) = serde_json::from_str::<Value>(&line) {
                if v.get("id").and_then(Value::as_u64) == Some(id) {
                    return v;
                }
            }
        }
    }

    fn sense(&mut self, id: u64, check: Value) -> Value {
        self.send(&json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": "tools/call",
            "params": { "name": "phoenix_sense", "arguments": { "check": check } }
        }));
        let response = self.response(id);
        let text = response["result"]["content"][0]["text"]
            .as_str()
            .unwrap_or_else(|| panic!("phoenix_sense returned no text: {response}"));
        serde_json::from_str(text).unwrap_or_else(|e| panic!("phoenix_sense returned non-JSON ({e}): {text}"))
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[test]
fn a_deadline_does_not_hand_the_check_the_servers_stdin() {
    let ws = tempfile::tempdir().unwrap();
    let mut server = Server::start(ws.path());
    server.send(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": { "name": "stdin-probe", "version": "1" }
        }
    }));
    server.response(1);
    server.send(&json!({ "jsonrpc": "2.0", "method": "notifications/initialized" }));

    // Control, with no deadline. If this is RED the fixture is broken and the assertion below would
    // prove nothing about the deadline path.
    let without = server.sense(2, json!({ "kind": "command_exit", "target": stdin_filter(), "expect": "0" }));
    assert_eq!(without["ok"], true, "the fixture fails even without a deadline: {without}");

    let with = server.sense(
        3,
        json!({ "kind": "command_exit", "target": stdin_filter(), "expect": "0", "timeout_secs": DEADLINE_SECS }),
    );
    assert_ne!(
        with["timed_out"],
        true,
        "declaring timeout_secs handed the check the server's stdin, which is the open JSON-RPC \
         channel, and the check blocked reading it until the deadline killed it: {with}"
    );
    assert_eq!(with["ok"], true, "the same check must pass with a deadline as it does without one: {with}");
}
