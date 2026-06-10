//! `snapshot` — capture last-good state, but ONLY if a check passes (never bless a bad state).

use crate::sense::{sense, Check, SenseResult};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnapshotResult {
    pub blessed: bool,
    pub snap_id: Option<String>,
    pub check: SenseResult,
}

fn snap_dir(workspace: &Path) -> PathBuf {
    workspace.join(".phoenix").join("snapshots")
}

/// Snapshot `path` only if `check` passes. The snapshot id encodes the file stem + a content hash so
/// rollbacks reference an explicit, blessed state (no silent "last snapshot might be bad" ambiguity).
pub fn snapshot(workspace: &Path, path: &Path, check: &Check) -> std::io::Result<SnapshotResult> {
    let res = sense(check);
    if !res.ok {
        return Ok(SnapshotResult { blessed: false, snap_id: None, check: res });
    }
    let dir = snap_dir(workspace);
    std::fs::create_dir_all(&dir)?;
    let digest = crate::sense::sha256_file(path)?;
    let stem = path.file_name().and_then(|s| s.to_str()).unwrap_or("file");
    let snap_id = format!("{stem}.{}", &digest[..16.min(digest.len())]);
    std::fs::copy(path, dir.join(&snap_id))?;
    Ok(SnapshotResult { blessed: true, snap_id: Some(snap_id), check: res })
}

/// Restore a blessed snapshot back to `path`, atomically (temp file + rename).
pub fn restore(workspace: &Path, path: &Path, snap_id: &str) -> std::io::Result<()> {
    let src = snap_dir(workspace).join(snap_id);
    if !src.exists() {
        return Err(std::io::Error::new(std::io::ErrorKind::NotFound, format!("snapshot {snap_id} missing")));
    }
    let tmp = path.with_extension("phoenix.tmp");
    std::fs::copy(&src, &tmp)?;
    std::fs::rename(&tmp, path)?; // atomic on same filesystem
    Ok(())
}
