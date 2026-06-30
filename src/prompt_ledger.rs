//! `prompt_ledger` — a content-addressed manifest over Phoenix's own prompt surface (skills + AGENTS.md),
//! and an objective drift check. The "living prompt document": capture once, then SENSE drift — RED on any
//! added/removed/changed prompt file, GREEN when the surface matches the blessed baseline. It is an ordinary
//! `Check` (`CheckKind::PromptManifest`), so it flows through the same `trace` / `accept` spine as every other
//! Phoenix check: `phoenix_accept` can prove a prompt check went red→green, the chain audits it.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::sense::sha256_file;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManifestEntry {
    /// Workspace-relative, forward-slash-normalized path.
    pub path: String,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub version: u32,
    pub generated_ts: String,
    /// Dirs (recursed) or single files, workspace-relative.
    pub roots: Vec<String>,
    /// File-name suffixes kept when recursing dirs (e.g. `.md`); empty = keep all files.
    pub ext_filter: Vec<String>,
    pub files: Vec<ManifestEntry>,
    /// sha256 over the sorted `relpath:sha256\n` lines — one stable digest for the whole surface.
    pub composite_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Verdict {
    pub ok: bool,
    pub added: Vec<String>,
    pub removed: Vec<String>,
    pub changed: Vec<String>,
}

fn norm(rel: &Path) -> String {
    rel.to_string_lossy().replace('\\', "/")
}

fn ext_ok(path: &Path, ext_filter: &[String]) -> bool {
    if ext_filter.is_empty() {
        return true;
    }
    let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
    ext_filter.iter().any(|e| name.ends_with(e.as_str()))
}

/// Collect workspace-relative file paths under `root_rel` (a dir, recursed) or the file itself.
fn collect(workspace: &Path, root_rel: &str, ext_filter: &[String], out: &mut Vec<String>) {
    let abs = workspace.join(root_rel);
    if abs.is_file() {
        out.push(norm(Path::new(root_rel)));
        return;
    }
    let mut stack = vec![abs];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&dir) else { continue };
        for entry in rd.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.is_file() && ext_ok(&p, ext_filter) {
                if let Ok(rel) = p.strip_prefix(workspace) {
                    out.push(norm(rel));
                }
            }
        }
    }
}

fn composite(entries: &[ManifestEntry]) -> String {
    use sha2::{Digest, Sha256};
    let mut lines: Vec<String> = entries
        .iter()
        .map(|e| format!("{}:{}", e.path, e.sha256))
        .collect();
    lines.sort();
    let mut h = Sha256::new();
    for l in &lines {
        h.update(l.as_bytes());
        h.update(b"\n");
    }
    let d = h.finalize();
    let mut s = String::with_capacity(d.len() * 2);
    for b in d {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

/// Capture a manifest of `roots` under `workspace`. Deterministic: entries are sorted by path, so an
/// unchanged tree always yields the same `composite_sha256`.
pub fn capture(workspace: &Path, roots: &[String], ext_filter: &[String]) -> std::io::Result<Manifest> {
    let mut rels: Vec<String> = Vec::new();
    for r in roots {
        collect(workspace, r, ext_filter, &mut rels);
    }
    rels.sort();
    rels.dedup();
    let mut files = Vec::with_capacity(rels.len());
    for rel in &rels {
        let sha = sha256_file(&workspace.join(rel))?;
        files.push(ManifestEntry { path: rel.clone(), sha256: sha });
    }
    let composite_sha256 = composite(&files);
    Ok(Manifest {
        version: 1,
        generated_ts: crate::trace::ts(),
        roots: roots.to_vec(),
        ext_filter: ext_filter.to_vec(),
        files,
        composite_sha256,
    })
}

pub fn write_manifest(path: &Path, m: &Manifest) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    std::fs::write(path, serde_json::to_string_pretty(m).unwrap_or_default())
}

pub fn read_manifest(path: &Path) -> std::io::Result<Manifest> {
    let s = std::fs::read_to_string(path)?;
    serde_json::from_str(&s).map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
}

/// The workspace is the parent of the `.phoenix` directory the manifest lives under, so a check that
/// only carries the manifest path is self-locating (works in the MCP path and in hermetic tests alike).
pub fn workspace_of_manifest(manifest_path: &Path) -> PathBuf {
    let mut cur = manifest_path;
    while let Some(parent) = cur.parent() {
        if parent.file_name().map(|n| n == std::ffi::OsStr::new(".phoenix")).unwrap_or(false) {
            if let Some(ws) = parent.parent() {
                return ws.to_path_buf();
            }
        }
        cur = parent;
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

/// Read a baseline manifest from disk and diff the current tree against it.
pub fn verify_manifest_file(manifest_path: &Path) -> std::io::Result<(Manifest, Verdict)> {
    let m = read_manifest(manifest_path)?;
    let ws = workspace_of_manifest(manifest_path);
    let v = verify_against(&ws, &m);
    Ok((m, v))
}

/// Diff the current tree (re-walking the manifest's own roots) against `baseline`.
/// `ok` iff nothing was added, removed, or changed.
pub fn verify_against(workspace: &Path, baseline: &Manifest) -> Verdict {
    let mut cur_rels: Vec<String> = Vec::new();
    for r in &baseline.roots {
        collect(workspace, r, &baseline.ext_filter, &mut cur_rels);
    }
    cur_rels.sort();
    cur_rels.dedup();

    let mut current: BTreeMap<String, String> = BTreeMap::new();
    for rel in &cur_rels {
        if let Ok(sha) = sha256_file(&workspace.join(rel)) {
            current.insert(rel.clone(), sha);
        }
    }
    let baseline_map: BTreeMap<&str, &str> = baseline
        .files
        .iter()
        .map(|e| (e.path.as_str(), e.sha256.as_str()))
        .collect();

    let mut added = Vec::new();
    let mut changed = Vec::new();
    for (path, sha) in &current {
        match baseline_map.get(path.as_str()) {
            None => added.push(path.clone()),
            Some(bsha) if *bsha != sha.as_str() => changed.push(path.clone()),
            _ => {}
        }
    }
    let mut removed = Vec::new();
    for e in &baseline.files {
        if !current.contains_key(&e.path) {
            removed.push(e.path.clone());
        }
    }
    added.sort();
    removed.sort();
    changed.sort();
    let ok = added.is_empty() && removed.is_empty() && changed.is_empty();
    Verdict { ok, added, removed, changed }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::accept::verify_gate;
    use crate::sense::{canonical_digest, sense, Check, CheckKind};
    use crate::trace::Trace;

    fn write(p: &Path, s: &str) {
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, s).unwrap();
    }

    #[test]
    fn capture_is_deterministic_and_detects_drift() {
        let tmp = tempfile::tempdir().unwrap();
        let ws = tmp.path();
        write(&ws.join("skills/a/SKILL.md"), "alpha\n");
        write(&ws.join("skills/b/SKILL.md"), "beta\n");
        write(&ws.join("AGENTS.md"), "charter\n");

        let roots = vec!["skills".to_string(), "AGENTS.md".to_string()];
        let ext = vec![".md".to_string()];
        let m = capture(ws, &roots, &ext).unwrap();
        assert_eq!(m.files.len(), 3, "should capture 3 .md files");

        // Deterministic: an unchanged tree yields the same composite.
        let m2 = capture(ws, &roots, &ext).unwrap();
        assert_eq!(m.composite_sha256, m2.composite_sha256);

        // No drift => GREEN.
        let v = verify_against(ws, &m);
        assert!(v.ok, "fresh capture must be GREEN, got {v:?}");

        // Change a tracked file => RED, named on `changed`.
        write(&ws.join("skills/a/SKILL.md"), "alpha-EDITED\n");
        let v = verify_against(ws, &m);
        assert!(!v.ok);
        assert_eq!(v.changed, vec!["skills/a/SKILL.md".to_string()]);

        // Add one, remove one => named on `added` / `removed`.
        write(&ws.join("skills/a/SKILL.md"), "alpha\n"); // restore
        write(&ws.join("skills/c/SKILL.md"), "gamma\n"); // add
        std::fs::remove_file(ws.join("skills/b/SKILL.md")).unwrap(); // remove
        let v = verify_against(ws, &m);
        assert!(!v.ok);
        assert!(v.added.contains(&"skills/c/SKILL.md".to_string()), "added={:?}", v.added);
        assert!(v.removed.contains(&"skills/b/SKILL.md".to_string()), "removed={:?}", v.removed);
    }

    #[test]
    fn prompt_manifest_check_proves_red_then_green_in_trace() {
        let tmp = tempfile::tempdir().unwrap();
        let ws = tmp.path();
        write(&ws.join("skills/a/SKILL.md"), "alpha\n");
        write(&ws.join("AGENTS.md"), "charter\n");
        let roots = vec!["skills".to_string(), "AGENTS.md".to_string()];
        let ext = vec![".md".to_string()];
        let m = capture(ws, &roots, &ext).unwrap();
        let manifest_path = ws.join(".phoenix/prompt-ledger/baseline.json");
        write_manifest(&manifest_path, &m).unwrap();

        let check = Check {
            kind: CheckKind::PromptManifest,
            target: vec![manifest_path.to_string_lossy().to_string()],
            expect: None,
            cwd: None,
            timeout_secs: None,
        };
        let tr = Trace::default_in(ws);

        // RED: introduce drift; sense must fail; record it.
        write(&ws.join("skills/a/SKILL.md"), "alpha-DRIFT\n");
        let r = sense(&check);
        assert!(!r.ok, "drift must sense RED");
        tr.append("sense", &canonical_digest(&check), r.ok, &r.signal, &r.evidence).unwrap();

        // GREEN: heal the drift; sense must pass; record it.
        write(&ws.join("skills/a/SKILL.md"), "alpha\n");
        let r = sense(&check);
        assert!(r.ok, "restored tree must sense GREEN: {}", r.evidence);
        tr.append("sense", &canonical_digest(&check), r.ok, &r.signal, &r.evidence).unwrap();

        // ACCEPT: completion derived from the trace, failure-first.
        let g = verify_gate(ws, &check);
        assert!(g.ok, "verify_gate must prove red->green: {}", g.reason);
        assert!(g.saw_red && g.green_after_red && g.currently_green && g.trace_intact);
    }
}
