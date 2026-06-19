//! Build-time embedding of Phoenix's shipped reference (the single source of truth):
//! the agent template (`dist/phoenix.agent.md`) and every bundled skill (`skills/<name>/SKILL.md`).
//! `doctor` compares the *installed* copies against these to detect drift, and `doctor --fix`
//! rewrites from them — so the binary is self-contained and needs no repo at runtime.

use std::{env, fs, path::Path};

fn main() {
    let manifest = env::var("CARGO_MANIFEST_DIR").unwrap();
    let out = env::var("OUT_DIR").unwrap();
    let dest = Path::new(&out).join("embedded.rs");

    let agent_path = format!("{manifest}/dist/phoenix.agent.md");
    println!("cargo:rerun-if-changed={agent_path}");

    let skills_dir = Path::new(&manifest).join("skills");
    // Watch the dir itself so ADDING or REMOVING a skill re-triggers embedding, not just edits.
    println!("cargo:rerun-if-changed={}", skills_dir.display().to_string().replace('\\', "/"));
    let mut entries: Vec<_> = fs::read_dir(&skills_dir)
        .expect("skills/ dir must exist")
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_dir())
        .collect();
    entries.sort_by_key(|e| e.file_name());

    let mut skills_src = String::new();
    for e in entries {
        let name = e.file_name().to_string_lossy().to_string();
        let skill_md = e.path().join("SKILL.md");
        if skill_md.exists() {
            let p = skill_md.display().to_string().replace('\\', "/");
            println!("cargo:rerun-if-changed={p}");
            skills_src.push_str(&format!("    ({name:?}, include_str!({p:?})),\n"));
        }
    }

    let agent_inc = agent_path.replace('\\', "/");
    let code = format!(
        "/// Shipped agent template (with the `__PHOENIX_BIN__` placeholder).\n\
         pub static AGENT_TEMPLATE: &str = include_str!({agent_inc:?});\n\
         /// Shipped skills as (name, SKILL.md) pairs, sorted by name.\n\
         pub static SKILLS: &[(&str, &str)] = &[\n{skills_src}];\n"
    );
    fs::write(&dest, code).expect("write embedded.rs");
    println!("cargo:rerun-if-changed=build.rs");
}
