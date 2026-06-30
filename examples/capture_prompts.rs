//! Regenerate Phoenix's "living prompt document" — a content-addressed manifest over its own prompt
//! surface (the 18 skills + the build charter). Run from the repo root:
//!
//!   cargo run --example capture_prompts
//!
//! Writes `docs/prompt-ledger/phoenix-prompts.json` (the version-controlled living document). Sense drift
//! against it any time (run from the repo root) with:
//!   phoenix-mcp sense '{"kind":"prompt_manifest","target":["docs/prompt-ledger/phoenix-prompts.json"]}'

use std::path::Path;

fn main() -> std::io::Result<()> {
    let workspace = std::env::current_dir()?;
    let roots = vec!["skills".to_string(), "AGENTS.md".to_string()];
    let ext_filter = vec![".md".to_string()];

    let manifest = phoenix::prompt_ledger::capture(&workspace, &roots, &ext_filter)?;
    let out = workspace.join("docs/prompt-ledger/phoenix-prompts.json");
    phoenix::prompt_ledger::write_manifest(&out, &manifest)?;

    eprintln!(
        "captured {} prompt files; composite={}",
        manifest.files.len(),
        manifest.composite_sha256
    );
    eprintln!("living prompt document -> {}", Path::new("docs/prompt-ledger/phoenix-prompts.json").display());
    Ok(())
}
