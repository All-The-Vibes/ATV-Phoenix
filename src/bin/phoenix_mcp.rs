//! phoenix-mcp — GitHub Copilot-facing MCP server (stdio) wrapping the proven Phoenix spine.
//!
//! Exposes four tools to Copilot via `/mcp`: phoenix_sense, phoenix_snapshot, phoenix_heal,
//! phoenix_verify_trace. The spine logic lives in the `phoenix` lib (proven by `cargo test`, M1);
//! this binary is the thin MCP adapter so Copilot can call sense/heal mid-task.
//!
//! CRITICAL: stdout is JSON-RPC ONLY. All diagnostics go to stderr.

use std::path::PathBuf;

use phoenix::sense::{sense, Check};
use phoenix::snapshot::snapshot;
use phoenix::{heal, HealCtx, Strategy, Trace};

use rmcp::{
    ServerHandler, ServiceExt,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{ServerCapabilities, ServerInfo},
    tool, tool_handler, tool_router,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// Workspace root for snapshots + trace. Defaults to CWD; override with PHOENIX_WORKSPACE.
fn workspace() -> PathBuf {
    std::env::var("PHOENIX_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn trace() -> Trace {
    Trace::default_in(&workspace())
}

fn jdigest(s: &str) -> String {
    phoenix::trace::digest_str(s)
}

// ---- tool parameter types (JSON-schema'd for Copilot) ----

#[derive(Serialize, Deserialize, JsonSchema)]
pub struct SenseArgs {
    /// The objective check to run.
    pub check: Check,
}

#[derive(Serialize, Deserialize, JsonSchema)]
pub struct SnapshotArgs {
    /// Path to the file to snapshot as last-good (relative to the workspace).
    pub path: String,
    /// The check that must pass for the snapshot to be blessed.
    pub check: Check,
}

#[derive(Serialize, Deserialize, JsonSchema)]
pub struct HealArgs {
    /// "rollback" or "retry".
    pub strategy: Strategy,
    /// Recovery context (path+snap_id for rollback, command for retry) and the external recheck.
    pub ctx: HealCtx,
}

#[derive(Clone)]
pub struct Phoenix {
    tool_router: ToolRouter<Self>,
}

#[tool_router(router = tool_router)]
impl Phoenix {
    pub fn new() -> Self {
        Self { tool_router: Self::tool_router() }
    }

    /// Objectively sense whether a check passes (no self-grading).
    #[tool(description = "Objectively check if a task succeeded. EXAMPLE call: {\"check\":{\"kind\":\"command_exit\",\"target\":[\"pytest\",\"-q\"],\"expect\":0}}. kind is one of command_exit (target=argv array, passes iff exit code==expect), file_sha256 (target=[path], expect=hex), regex_in_file (target=[path], expect=pattern). Returns {ok, signal, evidence}. No self-grading.")]
    async fn phoenix_sense(&self, args: Parameters<SenseArgs>) -> String {
        let r = sense(&args.0.check);
        let _ = trace().append("sense", &jdigest(&format!("{:?}", args.0.check.target)), r.ok, &r.signal, &r.evidence);
        serde_json::to_string(&r).unwrap_or_else(|e| format!("{{\"error\":\"{e}\"}}"))
    }

    /// Snapshot a file as last-good only if a check passes.
    #[tool(description = "Snapshot a file as last-good, but ONLY if the given check passes (never blesses a bad state). Returns JSON {blessed, snap_id}.")]
    async fn phoenix_snapshot(&self, args: Parameters<SnapshotArgs>) -> String {
        let ws = workspace();
        let path = ws.join(&args.0.path);
        match snapshot(&ws, &path, &args.0.check) {
            Ok(s) => {
                let _ = trace().append("snapshot", &jdigest(&args.0.path), s.blessed, "snapshot", &format!("blessed={}", s.blessed));
                serde_json::to_string(&s).unwrap_or_default()
            }
            Err(e) => format!("{{\"blessed\":false,\"error\":\"{e}\"}}"),
        }
    }

    /// Bounded recovery validated by an external recheck.
    #[tool(description = "Bounded recovery: rollback a file to a blessed snapshot, or retry a command (<=3). Recovery is confirmed by an EXTERNAL recheck. Returns JSON {healed, attempts, action}.")]
    async fn phoenix_heal(&self, args: Parameters<HealArgs>) -> String {
        let ws = workspace();
        let r = heal(&ws, args.0.strategy, &args.0.ctx);
        let _ = trace().append("heal", &jdigest(&r.action), r.healed, "heal", &r.evidence);
        serde_json::to_string(&r).unwrap_or_default()
    }

    /// Verify the tamper-evident hash-chained trace.
    #[tool(description = "Verify the tamper-evident hash-chained trace. Returns JSON {ok, rows, head_hash, broken_at}.")]
    async fn phoenix_verify_trace(&self) -> String {
        let v = trace().verify();
        serde_json::to_string(&v).unwrap_or_default()
    }
}

#[tool_handler(router = self.tool_router)]
impl ServerHandler for Phoenix {
    fn get_info(&self) -> ServerInfo {
        let mut info = ServerInfo::default();
        info.instructions = Some(
            "ATV-Phoenix self-healing spine. Use phoenix_sense to objectively check success, \
             phoenix_snapshot to save a blessed last-good state, phoenix_heal to recover \
             (bounded), and phoenix_verify_trace to audit. Prefer sensing over self-judging."
                .into(),
        );
        info.capabilities = ServerCapabilities::builder().enable_tools().build();
        info
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    // CLI mode (for hosts without external-MCP support, e.g. Microsoft Scout via its shell tool):
    //   phoenix-mcp sense '<check-json>'        -> prints SenseResult; exit 0 if ok else 1
    //   phoenix-mcp snapshot <path> '<check-json>'
    //   phoenix-mcp heal <rollback|retry> '<ctx-json>'
    //   phoenix-mcp verify-trace
    // MCP server mode (for GitHub Copilot via /mcp): no subcommand (or `serve`).
    if args.len() > 1 && args[1] != "serve" {
        return run_cli(&args);
    }
    eprintln!("phoenix-mcp v0 starting (stdio MCP). workspace={}", workspace().display());
    let service = Phoenix::new().serve(rmcp::transport::stdio()).await?;
    service.waiting().await?;
    Ok(())
}

fn run_cli(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let ws = workspace();
    let exit = |ok: bool| -> ! { std::process::exit(if ok { 0 } else { 1 }) };
    match args[1].as_str() {
        "sense" => {
            let check: Check = serde_json::from_str(&args[2])?;
            let r = sense(&check);
            let _ = trace().append("sense", &jdigest(&args[2]), r.ok, &r.signal, &r.evidence);
            println!("{}", serde_json::to_string(&r)?);
            exit(r.ok);
        }
        "snapshot" => {
            let path = ws.join(&args[2]);
            let check: Check = serde_json::from_str(&args[3])?;
            let s = snapshot(&ws, &path, &check)?;
            let _ = trace().append("snapshot", &jdigest(&args[2]), s.blessed, "snapshot", &format!("blessed={}", s.blessed));
            println!("{}", serde_json::to_string(&s)?);
            exit(s.blessed);
        }
        "heal" => {
            let strat: Strategy = serde_json::from_str(&format!("\"{}\"", args[2]))?;
            let ctx: HealCtx = serde_json::from_str(&args[3])?;
            let r = heal(&ws, strat, &ctx);
            let _ = trace().append("heal", &jdigest(&r.action), r.healed, "heal", &r.evidence);
            println!("{}", serde_json::to_string(&r)?);
            exit(r.healed);
        }
        "verify-trace" => {
            let v = trace().verify();
            println!("{}", serde_json::to_string(&v)?);
            exit(v.ok);
        }
        "--version" | "-V" => {
            println!("phoenix {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        other => {
            eprintln!("phoenix: unknown subcommand '{other}'. Use: sense|snapshot|heal|verify-trace|serve");
            std::process::exit(2);
        }
    }
}
