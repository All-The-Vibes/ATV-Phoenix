//! `doctor` — Phoenix's self-maintenance: validate (and report on) Phoenix's own install using the
//! same objective-evidence discipline it gives the agent. A self-healing harness must be able to
//! verify itself; this is that check.
//!
//! Two layers:
//!   * **skills frontmatter** (`doctor`/`check_skill_file`) — every bundled SKILL.md is well-formed.
//!     Drift here fails `cargo test`, so the harness catches its own rot.
//!   * **install integrity** (`integrity`/`fix`) — the *installed* agent, skills, and MCP registration
//!     match what THIS build ships (embedded at build time). Catches the whole class of "installed
//!     before a fix" bugs generically — no per-field hardcoding — and `fix` re-syncs from the embedded
//!     reference, confirmed by re-running the same check (red -> green).

use serde::{Deserialize, Serialize};
use std::path::Path;

/// Placeholder in the shipped agent template, replaced with the real binary path at install/fix time.
pub const PLACEHOLDER: &str = "__PHOENIX_BIN__";

/// The shipped reference (agent template + every bundled skill), embedded at build time by `build.rs`.
/// This is the single source of truth `doctor` compares the installed copies against.
pub mod embedded {
    include!(concat!(env!("OUT_DIR"), "/embedded.rs"));
}

/// The agent template this build ships (contains the `__PHOENIX_BIN__` placeholder).
pub fn shipped_agent_template() -> &'static str {
    embedded::AGENT_TEMPLATE
}

/// The skills this build ships, as `(name, SKILL.md)` pairs.
pub fn shipped_skills() -> &'static [(&'static str, &'static str)] {
    embedded::SKILLS
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillReport {
    pub name: String,
    pub ok: bool,
    pub problems: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DoctorReport {
    pub ok: bool,
    pub skills_checked: usize,
    pub skills: Vec<SkillReport>,
}

/// Validate one SKILL.md's agentskills.io frontmatter: must have a `---` block containing non-empty
/// `name:` and `description:` keys, and the name must match its directory.
pub fn check_skill_file(dir_name: &str, content: &str) -> SkillReport {
    let mut problems = Vec::new();
    let trimmed = content.trim_start();
    if !trimmed.starts_with("---") {
        problems.push("missing opening `---` frontmatter".into());
    }
    // extract the frontmatter block between the first two `---` lines
    let mut in_fm = false;
    let mut fm_lines: Vec<&str> = Vec::new();
    let mut closed = false;
    for line in content.lines() {
        if line.trim() == "---" {
            if !in_fm {
                in_fm = true;
                continue;
            } else {
                closed = true;
                break;
            }
        }
        if in_fm {
            fm_lines.push(line);
        }
    }
    if !closed {
        problems.push("frontmatter not closed with `---`".into());
    }
    let name = fm_lines
        .iter()
        .find_map(|l| l.trim().strip_prefix("name:").map(|v| v.trim().to_string()));
    let desc = fm_lines
        .iter()
        .find_map(|l| l.trim().strip_prefix("description:").map(|v| v.trim().to_string()));
    match &name {
        None => problems.push("missing `name:`".into()),
        Some(n) if n.is_empty() => problems.push("empty `name:`".into()),
        Some(n) if n != dir_name => problems.push(format!("name '{n}' != directory '{dir_name}'")),
        _ => {}
    }
    match &desc {
        None => problems.push("missing `description:`".into()),
        Some(d) if d.len() < 20 => problems.push("description too short (<20 chars)".into()),
        _ => {}
    }
    SkillReport { name: name.unwrap_or_else(|| dir_name.to_string()), ok: problems.is_empty(), problems }
}

/// Validate every bundled skill under `skills_dir/<name>/SKILL.md`.
pub fn doctor(skills_dir: &Path) -> DoctorReport {
    let mut skills = Vec::new();
    if let Ok(entries) = std::fs::read_dir(skills_dir) {
        let mut dirs: Vec<_> = entries.flatten().filter(|e| e.path().is_dir()).collect();
        dirs.sort_by_key(|e| e.file_name());
        for e in dirs {
            let dir_name = e.file_name().to_string_lossy().to_string();
            let skill_md = e.path().join("SKILL.md");
            if !skill_md.exists() {
                skills.push(SkillReport { name: dir_name.clone(), ok: false, problems: vec!["no SKILL.md".into()] });
                continue;
            }
            match std::fs::read_to_string(&skill_md) {
                Ok(c) => skills.push(check_skill_file(&dir_name, &c)),
                Err(err) => skills.push(SkillReport { name: dir_name, ok: false, problems: vec![format!("read error: {err}")] }),
            }
        }
    }
    let ok = !skills.is_empty() && skills.iter().all(|s| s.ok);
    DoctorReport { ok, skills_checked: skills.len(), skills }
}

// ---------------------------------------------------------------------------
// Install-integrity layer: does the INSTALLED Phoenix match what this build ships?
// ---------------------------------------------------------------------------

/// One install-integrity check, shaped like a `phoenix_sense` result: objective, with evidence.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckReport {
    pub check: String,
    pub ok: bool,
    pub fixable: bool,
    pub evidence: String,
    pub problems: Vec<String>,
}

/// The full install-integrity report (all checks + roll-up).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstallReport {
    pub ok: bool,
    pub checks: Vec<CheckReport>,
}

/// Normalize file content so equal installs compare equal: LF line endings, no trailing whitespace,
/// exactly one trailing newline.
fn norm(text: &str) -> String {
    let t = text.replace("\r\n", "\n").replace('\r', "\n");
    let joined: Vec<&str> = t.split('\n').map(|l| l.trim_end()).collect();
    format!("{}\n", joined.join("\n").trim_end_matches('\n'))
}

/// Normalize an agent file for content comparison: `norm`, plus replace the machine-specific
/// `command:` line value with the placeholder so a correct install on any machine matches the
/// shipped template. (Whether that path actually resolves is a SEPARATE check — see mcp-config.)
fn canon_agent(text: &str) -> String {
    let n = norm(text);
    let re = regex::Regex::new(r"(?m)^(\s*command:\s*).*$").unwrap();
    re.replace_all(&n, "${1}__PHOENIX_BIN__").into_owned()
}

fn short_sha(s: &str) -> String {
    use sha2::{Digest, Sha256};
    let d = Sha256::digest(s.as_bytes());
    d.iter().take(6).map(|b| format!("{b:02x}")).collect()
}

/// Resolve Phoenix's Copilot home (where agents/, skills/, mcp-config.json live):
/// explicit arg > `$COPILOT_HOME` > `~/.copilot`.
pub fn resolve_home(explicit: Option<&Path>) -> std::path::PathBuf {
    if let Some(p) = explicit {
        return p.to_path_buf();
    }
    if let Ok(h) = std::env::var("COPILOT_HOME") {
        return std::path::PathBuf::from(h);
    }
    let home = std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .unwrap_or_else(|_| ".".into());
    std::path::PathBuf::from(home).join(".copilot")
}

/// Check the installed agent matches the shipped template (content drift, path-independent).
pub fn check_agent(home: &Path) -> CheckReport {
    let inst = home.join("agents").join("phoenix.agent.md");
    if !inst.exists() {
        return CheckReport {
            check: "agent".into(),
            ok: false,
            fixable: true,
            evidence: format!("{} does not exist", inst.display()),
            problems: vec!["phoenix agent is not installed (run with --fix)".into()],
        };
    }
    let installed = std::fs::read_to_string(&inst).unwrap_or_default();
    let a = canon_agent(&installed);
    let b = canon_agent(shipped_agent_template());
    let mut problems = Vec::new();
    if a != b {
        problems.push(
            "installed agent differs from the shipped template (stale install or hand-edit); re-sync with --fix".into(),
        );
    }
    CheckReport {
        check: "agent".into(),
        ok: problems.is_empty(),
        fixable: true,
        evidence: format!("installed={} shipped={}", short_sha(&a), short_sha(&b)),
        problems,
    }
}

/// Check every shipped skill is installed and byte-matches (after normalization) the shipped copy.
pub fn check_skills_integrity(home: &Path) -> CheckReport {
    let inst_dir = home.join("skills");
    let (mut missing, mut drifted, mut invalid) = (Vec::new(), Vec::new(), Vec::new());
    for (name, content) in shipped_skills() {
        let p = inst_dir.join(name).join("SKILL.md");
        if !p.exists() {
            missing.push(name.to_string());
            continue;
        }
        let installed = std::fs::read_to_string(&p).unwrap_or_default();
        if !check_skill_file(name, &installed).ok {
            invalid.push(name.to_string());
        }
        if norm(&installed) != norm(content) {
            drifted.push(name.to_string());
        }
    }
    let total = shipped_skills().len();
    let matched = total - missing.len() - drifted.len();
    let mut problems = Vec::new();
    if !missing.is_empty() {
        problems.push(format!("missing: {}", missing.join(", ")));
    }
    if !drifted.is_empty() {
        problems.push(format!("drifted from shipped: {}", drifted.join(", ")));
    }
    if !invalid.is_empty() {
        problems.push(format!("invalid frontmatter: {}", invalid.join(", ")));
    }
    CheckReport {
        check: "skills".into(),
        ok: problems.is_empty(),
        fixable: true,
        evidence: format!("{matched}/{total} match shipped"),
        problems,
    }
}

/// Check the `phoenix` MCP server is registered in mcp-config.json and its binary resolves.
pub fn check_mcp_config(home: &Path) -> CheckReport {
    let cfg = home.join("mcp-config.json");
    if !cfg.exists() {
        return CheckReport {
            check: "mcp-config".into(),
            ok: false,
            fixable: true,
            evidence: format!("{} not found", cfg.display()),
            problems: vec!["phoenix MCP server is not registered (run with --fix)".into()],
        };
    }
    let txt = std::fs::read_to_string(&cfg).unwrap_or_default();
    let mut problems = Vec::new();
    let mut evidence = String::new();
    match serde_json::from_str::<serde_json::Value>(&txt) {
        Err(e) => problems.push(format!("mcp-config.json is not valid JSON: {e}")),
        Ok(v) => match v.get("mcpServers").and_then(|m| m.get("phoenix")) {
            None => problems.push("no `phoenix` entry under mcpServers; re-register with --fix".into()),
            Some(s) => {
                let cmd = s.get("command").and_then(|c| c.as_str()).unwrap_or("");
                evidence = format!("command={cmd}");
                if cmd.is_empty() {
                    problems.push("phoenix server has no command".into());
                } else if !Path::new(cmd).exists() {
                    problems.push(format!("phoenix server binary not found at {cmd}; re-register with --fix"));
                }
            }
        },
    }
    CheckReport {
        check: "mcp-config".into(),
        ok: problems.is_empty(),
        fixable: true,
        evidence,
        problems,
    }
}

/// Run the full install-integrity check against `home`.
pub fn integrity(home: &Path) -> InstallReport {
    let checks = vec![
        check_agent(home),
        check_skills_integrity(home),
        check_mcp_config(home),
    ];
    let ok = checks.iter().all(|c| c.ok);
    InstallReport { ok, checks }
}

/// Re-sync the install from the embedded reference. Idempotent. `binpath` is the phoenix-mcp binary
/// to wire into the agent + mcp-config (normally `current_exe()`). Snapshots the prior agent +
/// mcp-config as `*.doctor-bak` before overwriting (heal discipline). Returns the actions taken.
pub fn fix(home: &Path, binpath: &Path) -> Vec<String> {
    let bin = binpath.display().to_string().replace('\\', "/");
    let mut actions = Vec::new();

    // agent
    let agents = home.join("agents");
    let _ = std::fs::create_dir_all(&agents);
    let agent_file = agents.join("phoenix.agent.md");
    let want = shipped_agent_template().replace(PLACEHOLDER, &bin);
    let cur = std::fs::read_to_string(&agent_file).unwrap_or_default();
    if norm(&cur) != norm(&want) {
        if agent_file.exists() {
            let _ = std::fs::copy(&agent_file, agents.join("phoenix.agent.md.doctor-bak"));
        }
        if std::fs::write(&agent_file, &want).is_ok() {
            actions.push("re-synced agents/phoenix.agent.md from shipped template".into());
        }
    }

    // skills
    let skills_dir = home.join("skills");
    for (name, content) in shipped_skills() {
        let dir = skills_dir.join(name);
        let _ = std::fs::create_dir_all(&dir);
        let f = dir.join("SKILL.md");
        let cur = std::fs::read_to_string(&f).unwrap_or_default();
        if norm(&cur) != norm(content) {
            if std::fs::write(&f, content).is_ok() {
                actions.push(format!("re-synced skill {name}"));
            }
        }
    }

    // mcp-config
    let cfg_path = home.join("mcp-config.json");
    let mut cfg: serde_json::Value = std::fs::read_to_string(&cfg_path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| serde_json::json!({"mcpServers": {}}));
    if !cfg.get("mcpServers").map(|m| m.is_object()).unwrap_or(false) {
        cfg["mcpServers"] = serde_json::json!({});
    }
    let needs = cfg["mcpServers"]
        .get("phoenix")
        .and_then(|s| s.get("command"))
        .and_then(|c| c.as_str())
        .map(|c| c != bin)
        .unwrap_or(true);
    if needs {
        if cfg_path.exists() {
            let _ = std::fs::copy(&cfg_path, home.join("mcp-config.json.doctor-bak"));
        }
        cfg["mcpServers"]["phoenix"] = serde_json::json!({"type": "stdio", "command": bin});
        if let Ok(s) = serde_json::to_string_pretty(&cfg) {
            if std::fs::write(&cfg_path, s).is_ok() {
                actions.push("registered phoenix MCP server in mcp-config.json".into());
            }
        }
    }

    actions
}
