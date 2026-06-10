//! phoenix-mcp — the MCP server entrypoint (v0 stub).
//!
//! The spine logic lives in the `phoenix` lib and is fully proven by `cargo test` (the behavioral
//! green->red->heal->green demo). MCP/stdio wiring via `rmcp` is layered on next; kept as a stub here
//! so the crate builds and the core is verifiable independently of protocol churn.

fn main() {
    eprintln!("phoenix-mcp v0: spine = sense/heal/snapshot/verify_trace (lib). MCP wiring: next step.");
    eprintln!("Run `cargo test` for the behavioral self-heal demo (M1 pass criterion).");
}
