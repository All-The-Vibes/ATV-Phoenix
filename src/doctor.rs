//! `doctor` — Phoenix's self-maintenance: validate (and report on) Phoenix's own bundled skills using
//! the same objective-evidence discipline it gives the agent. A self-healing harness must be able to
//! verify itself; this is that check. Drift in any bundled SKILL.md fails the check (and `cargo test`).

use serde::{Deserialize, Serialize};
use std::path::Path;

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
