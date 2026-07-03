//! phoenix-mcp — GitHub Copilot-facing MCP server (stdio) wrapping the proven Phoenix spine.
//!
//! Exposes five tools to Copilot via `/mcp`: phoenix_sense, phoenix_snapshot, phoenix_heal,
//! phoenix_verify_trace, phoenix_accept. The spine logic lives in the `phoenix` lib (proven by
//! `cargo test`, M1); this binary is the thin MCP adapter so Copilot can call sense/heal/accept mid-task.
//!
//! CRITICAL: stdout is JSON-RPC ONLY. All diagnostics go to stderr.

use std::path::PathBuf;

use phoenix::sense::{canonical_digest, sense, Check};
use phoenix::snapshot::snapshot;
use phoenix::{heal, HealCtx, Strategy, Trace};
use phoenix::intent::{verify_intent, IntentManifest};

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

#[derive(Serialize, Deserialize, JsonSchema)]
pub struct IntentAcceptArgs {
    /// Path to the intent manifest JSON file (relative to workspace), e.g. ".phoenix-intent/intent.json".
    pub manifest_path: String,
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
        let _ = trace().append("sense", &canonical_digest(&args.0.check), r.ok, &r.signal, &r.evidence);
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

    /// Prove a check is a SATISFIED acceptance gate from the trace (failure-first), not self-report.
    #[tool(description = "Decide DONE by PROOF, not opinion. Returns ok=true ONLY if the tamper-evident trace shows this exact check went red->green (failure-first) AND it is green now. Call this before claiming a task/goal is complete — it is the objective stop signal for an autonomous loop. A check never observed failing (a vacuous gate) returns ok=false. EXAMPLE: {\"check\":{\"kind\":\"command_exit\",\"target\":[\"pytest\",\"-q\"],\"expect\":0}}. Returns {ok, check_digest, trace_intact, saw_red, green_after_red, currently_green, reason}.")]
    async fn phoenix_accept(&self, args: Parameters<SenseArgs>) -> String {
        let g = phoenix::accept::verify_gate(&workspace(), &args.0.check);
        serde_json::to_string(&g).unwrap_or_else(|e| format!("{{\"error\":\"{e}\"}}"))
    }

    /// Prove composite completion for an N-goal intent manifest (failure-first for ALL goals).
    #[tool(description = "Composite DONE proof for a multi-goal intent. Reads an intent manifest JSON file and verifies that ALL goals are individually proven failure-first (each saw red→green on an intact per-goal trace and is currently green). Returns {ok, intent, goal_count, goals_ok, goals, reason}. ok=true only when every goal passes. Use after running per-goal phoenix-ralph loops with per-goal PHOENIX_WORKSPACE. EXAMPLE: {\"manifest_path\":\".phoenix-intent/intent.json\"}.")]
    async fn phoenix_intent_accept(&self, args: Parameters<IntentAcceptArgs>) -> String {
        let ws = workspace();
        let manifest_path = ws.join(&args.0.manifest_path);
        let manifest: IntentManifest = match std::fs::read_to_string(&manifest_path)
            .map_err(|e| e.to_string())
            .and_then(|s| serde_json::from_str(&s).map_err(|e| e.to_string()))
        {
            Ok(m) => m,
            Err(e) => return format!("{{\"ok\":false,\"error\":\"failed to read manifest: {e}\"}}"),
        };
        let result = verify_intent(&ws, &manifest);
        serde_json::to_string(&result).unwrap_or_else(|e| format!("{{\"error\":\"{e}\"}}"))
    }
}

#[tool_handler(router = self.tool_router)]
impl ServerHandler for Phoenix {
    fn get_info(&self) -> ServerInfo {
        let mut info = ServerInfo::default();
        info.instructions = Some(
            "ATV-Phoenix self-healing spine. Use phoenix_sense to objectively check success, \
             phoenix_snapshot to save a blessed last-good state, phoenix_heal to recover \
             (bounded), phoenix_verify_trace to audit, phoenix_accept to prove a single goal \
             done (failure-first), and phoenix_intent_accept to prove composite completion \
             for a multi-goal intent (all N goals failure-first)."
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
    //   phoenix-mcp accept '<check-json>'        -> gate ledger: exit 0 iff trace proves red->green + green now
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
    // JSON args may be passed inline OR as `@path/to/file.json`. The `@file` form avoids the
    // PowerShell/cmd → native-exe quote-mangling that corrupts inline JSON ("key must be a string");
    // the loop driver always uses `@file`.
    let jarg = |s: &str| -> std::io::Result<String> {
        if let Some(path) = s.strip_prefix('@') {
            std::fs::read_to_string(path)
        } else {
            Ok(s.to_string())
        }
    };
    match args[1].as_str() {
        "sense" => {
            let check: Check = serde_json::from_str(&jarg(&args[2])?)?;
            let r = sense(&check);
            let _ = trace().append("sense", &canonical_digest(&check), r.ok, &r.signal, &r.evidence);
            println!("{}", serde_json::to_string(&r)?);
            exit(r.ok);
        }
        "accept" => {
            // Gate ledger: is this check a SATISFIED acceptance gate, proven from the trace?
            // ok=true only if the trace shows it red→green (failure-first) and it is green now.
            // The driver — not the agent — calls this to decide completion.
            let check: Check = serde_json::from_str(&jarg(&args[2])?)?;
            let g = phoenix::accept::verify_gate(&ws, &check);
            println!("{}", serde_json::to_string(&g)?);
            exit(g.ok);
        }
        "snapshot" => {
            let path = ws.join(&args[2]);
            let check: Check = serde_json::from_str(&jarg(&args[3])?)?;
            let s = snapshot(&ws, &path, &check)?;
            let _ = trace().append("snapshot", &jdigest(&args[2]), s.blessed, "snapshot", &format!("blessed={}", s.blessed));
            println!("{}", serde_json::to_string(&s)?);
            exit(s.blessed);
        }
        "heal" => {
            let strat: Strategy = serde_json::from_str(&format!("\"{}\"", args[2]))?;
            let ctx: HealCtx = serde_json::from_str(&jarg(&args[3])?)?;
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
        "intent-accept" => {
            // Composite gate: are ALL goals in an intent manifest proven failure-first?
            // Reads <workspace>/<manifest_path> and verifies each goal against its per-goal trace.
            // ok=true only when every goal passes; exits 0 if composite ok, 1 otherwise.
            let manifest_path = ws.join(&args[2]);
            let manifest: IntentManifest = {
                let raw = std::fs::read_to_string(&manifest_path)
                    .map_err(|e| format!("cannot read {}: {e}", manifest_path.display()))?;
                serde_json::from_str(&raw)
                    .map_err(|e| format!("invalid intent manifest {}: {e}", manifest_path.display()))?
            };
            let result = verify_intent(&ws, &manifest);
            println!("{}", serde_json::to_string(&result)?);
            exit(result.ok);
        }
        "doctor" => {
            // Two modes:
            //   * legacy: `doctor <skills-dir>` validates one skills dir's frontmatter (back-compat).
            //   * install integrity: `doctor [--fix] [--home <dir>]` checks the INSTALLED agent +
            //     skills + MCP registration against what THIS build ships, and `--fix` re-syncs them.
            let rest = &args[2..];
            let legacy_dir = rest
                .iter()
                .find(|a| !a.starts_with("--"))
                .filter(|a| std::path::Path::new(a).is_dir() && a.ends_with("skills"));
            if let Some(dir) = legacy_dir {
                let r = phoenix::doctor(std::path::Path::new(dir));
                println!("{}", serde_json::to_string(&r)?);
                for s in &r.skills {
                    if !s.ok {
                        eprintln!("  [FAIL] {}: {}", s.name, s.problems.join("; "));
                    }
                }
                eprintln!("phoenix doctor: {}/{} skills OK", r.skills.iter().filter(|s| s.ok).count(), r.skills_checked);
                exit(r.ok);
            }

            let do_fix = rest.iter().any(|a| a == "--fix");
            let home_arg = rest.iter().position(|a| a == "--home").and_then(|i| rest.get(i + 1));
            let home = phoenix::doctor::resolve_home(home_arg.map(|a| std::path::Path::new(a.as_str())));

            if do_fix {
                let binpath = std::env::current_exe().unwrap_or_else(|_| std::path::PathBuf::from("phoenix-mcp"));
                let actions = phoenix::doctor::fix(&home, &binpath);
                if actions.is_empty() {
                    eprintln!("[fix] nothing to repair — install already matches shipped");
                } else {
                    for a in &actions {
                        eprintln!("[fix] {a}");
                    }
                }
            }

            let r = phoenix::doctor::integrity(&home);
            let bf = phoenix::doctor::build_freshness();
            let stale = bf.state == phoenix::doctor::Freshness::Behind;
            let overall = r.ok && !stale;
            // stdout JSON stays back-compatible (`ok` + `checks`) and is enriched with `build`.
            let mut jv = serde_json::to_value(&r)?;
            jv["ok"] = serde_json::json!(overall);
            jv["build"] = serde_json::to_value(&bf)?;
            println!("{}", serde_json::to_string(&jv)?);
            for c in &r.checks {
                let mark = if c.ok { "OK " } else { "RED" };
                eprintln!("  [{mark}] {}: {}", c.check, c.evidence);
                for p in &c.problems {
                    eprintln!("         - {p}");
                }
            }
            let bmark = match bf.state {
                phoenix::doctor::Freshness::UpToDate => "OK ",
                phoenix::doctor::Freshness::Behind => "WARN",
                phoenix::doctor::Freshness::Unknown => "-- ",
            };
            eprintln!("  [{bmark}] build: {}", bf.evidence);
            for p in &bf.problems {
                eprintln!("         - {p}");
            }
            let remedy = {
                let mut hints: Vec<&str> = Vec::new();
                if !r.ok {
                    hints.push("run `phoenix-mcp doctor --fix` to repair");
                }
                if stale {
                    hints.push("rebuild: `cargo build --release`");
                }
                if hints.is_empty() {
                    String::new()
                } else {
                    format!("  — {}", hints.join("; "))
                }
            };
            eprintln!(
                "phoenix doctor ({}): {}/{} checks OK{}",
                home.display(),
                r.checks.iter().filter(|c| c.ok).count(),
                r.checks.len(),
                remedy
            );
            exit(overall);
        }
        "--version" | "-V" => {
            println!("phoenix {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        other => {
            eprintln!("phoenix: unknown subcommand '{other}'. Use: sense|accept|intent-accept|snapshot|heal|verify-trace|doctor|serve");
            std::process::exit(2);
        }
    }
}
