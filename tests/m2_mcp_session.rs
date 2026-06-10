//! M2 — drive the phoenix-mcp server over real MCP stdio JSON-RPC in ONE session, injecting a fault
//! mid-stream, exactly as GitHub Copilot would call it. Proves sense+heal work THROUGH the protocol,
//! not just as a library. Trace stays consistent because it's a single server process.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

struct Server {
    child: Child,
    stdin: ChildStdin,
    out: BufReader<ChildStdout>,
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
        let out = BufReader::new(child.stdout.take().unwrap());
        Server { child, stdin, out }
    }

    fn send(&mut self, line: &str) {
        self.stdin.write_all(line.as_bytes()).unwrap();
        self.stdin.write_all(b"\n").unwrap();
        self.stdin.flush().unwrap();
    }

    /// Read newline-delimited JSON responses until we see one with the given id; return it.
    fn read_id(&mut self, id: u64) -> serde_json::Value {
        let mut line = String::new();
        loop {
            line.clear();
            let n = self.out.read_line(&mut line).unwrap();
            assert!(n > 0, "server closed stdout before id={id}");
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(line.trim()) {
                if v.get("id").and_then(|i| i.as_u64()) == Some(id) {
                    return v;
                }
            }
        }
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Extract the JSON the tool returned (tools/call wraps it in result.content[0].text).
fn tool_json(resp: &serde_json::Value) -> serde_json::Value {
    let text = resp["result"]["content"][0]["text"].as_str().unwrap_or("{}");
    serde_json::from_str(text).unwrap_or(serde_json::json!({}))
}

#[test]
fn copilot_drives_sense_and_heal_over_mcp() {
    let ws = tempfile::tempdir().unwrap();
    let logic = ws.path().join("logic.txt");
    std::fs::write(&logic, "answer=GOOD_MARKER\n").unwrap();

    // The external invariant: an OS command checks the file contains GOOD_MARKER.
    let target = if cfg!(windows) {
        format!(r#"["cmd","/C","findstr","/C:GOOD_MARKER","{}"]"#, logic.display().to_string().replace('\\', "\\\\"))
    } else {
        format!(r#"["grep","-q","GOOD_MARKER","{}"]"#, logic.display())
    };
    let check = format!(r#"{{"kind":"command_exit","target":{target},"expect":"0"}}"#);

    let mut s = Server::start(ws.path());
    s.send(r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"copilot-like","version":"1"}}}"#);
    s.read_id(1);
    s.send(r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#);

    // 1) sense baseline -> GREEN
    s.send(&format!(r#"{{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{{"name":"phoenix_sense","arguments":{{"check":{check}}}}}}}"#));
    let baseline = tool_json(&s.read_id(2));
    assert_eq!(baseline["ok"], true, "baseline should be green");

    // 2) snapshot -> blessed
    s.send(&format!(r#"{{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{{"name":"phoenix_snapshot","arguments":{{"path":"logic.txt","check":{check}}}}}}}"#));
    let snap = tool_json(&s.read_id(3));
    assert_eq!(snap["blessed"], true, "snapshot must be blessed");
    let snap_id = snap["snap_id"].as_str().unwrap().to_string();

    // 3) INJECT FAULT mid-session (Copilot's edit goes wrong)
    std::fs::write(&logic, "answer=BROKEN\n").unwrap();

    // 4) sense -> RED (detected via the external command)
    s.send(&format!(r#"{{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{{"name":"phoenix_sense","arguments":{{"check":{check}}}}}}}"#));
    let red = tool_json(&s.read_id(4));
    assert_eq!(red["ok"], false, "fault must be detected");

    // 5) heal rollback -> healed (validated by the external recheck)
    let ctx = format!(r#"{{"path":"logic.txt","snap_id":"{snap_id}","recheck":{check}}}"#);
    s.send(&format!(r#"{{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{{"name":"phoenix_heal","arguments":{{"strategy":"rollback","ctx":{ctx}}}}}}}"#));
    let healed = tool_json(&s.read_id(5));
    assert_eq!(healed["healed"], true, "heal must restore passing behavior: {healed}");

    // 6) sense -> GREEN again
    s.send(&format!(r#"{{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{{"name":"phoenix_sense","arguments":{{"check":{check}}}}}}}"#));
    let recovered = tool_json(&s.read_id(6));
    assert_eq!(recovered["ok"], true, "must be green after heal");

    // 7) verify_trace -> intact, and it recorded the whole chain (>=5 events)
    s.send(r#"{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"phoenix_verify_trace","arguments":{}}}"#);
    let v = tool_json(&s.read_id(7));
    assert_eq!(v["ok"], true, "trace must verify: {v}");
    assert!(v["rows"].as_u64().unwrap() >= 5, "trace should hold the full chain, got {}", v["rows"]);
}
