//! `accept` — the gate ledger. Completion is **derived from the trace, never authored by the agent**.
//!
//! A check counts as a real acceptance gate only if the tamper-evident trace proves it was
//! **failure-first**: it was observed RED (failing) and *later* GREEN (passing) for the SAME
//! canonical check, the trace chain is intact, and it is still GREEN right now.
//!
//! This is what stops a *vacuous* check (e.g. `test -f file`, `echo ok`, a regex matching text that
//! was already present) from declaring victory: a gate that was never seen failing proves nothing.
//! It is the tooling-enforced version of the SWE-bench discipline "watch the check fail before you
//! trust it pass." The agent can *propose* that an item is done; only this function (run by the
//! driver) decides whether it actually is.

use crate::sense::{canonical_digest, sense, sha256_file, Check, CheckKind};
use crate::trace::Trace;
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
#[cfg(unix)]
use std::fs::File;
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GateResult {
    /// True only if: trace intact AND red-before-green for this exact check AND currently green.
    pub ok: bool,
    pub check_digest: String,
    pub trace_intact: bool,
    pub saw_red: bool,
    pub green_after_red: bool,
    pub currently_green: bool,
    pub reason: String,
}

/// Decide whether `check` is a satisfied acceptance gate, proven from the trace.
pub fn verify_gate(workspace: &Path, check: &Check) -> GateResult {
    let digest = canonical_digest(check);
    let tr = Trace::default_in(workspace);

    // 1. The chain must be intact — a tampered trace (e.g. an injected fake "green") is rejected.
    let v = tr.verify();
    let trace_intact = v.ok;

    // 2. Walk the trace in order: find a RED sense for THIS exact check, then a later GREEN.
    let mut saw_red = false;
    let mut green_after_red = false;
    for ev in tr.read_all() {
        if ev.tool != "sense" || ev.input_digest != digest {
            continue;
        }
        if !ev.ok {
            saw_red = true;
        } else if saw_red {
            green_after_red = true;
        }
    }

    // 3. Re-run the check now (read-only; does not append) — it must actually be green at decision time.
    let currently_green = sense(check).ok;

    let ok = trace_intact && saw_red && green_after_red && currently_green;
    let reason = if !trace_intact {
        format!("trace chain broken at row {:?} — completion cannot be trusted", v.broken_at)
    } else if !saw_red {
        "no RED observation for this check in the trace — a gate never seen failing proves nothing \
         (vacuous-check guard). Reproduce the failure first, then fix it."
            .into()
    } else if !green_after_red {
        "check was observed red but never green afterward — not yet satisfied".into()
    } else if !currently_green {
        "trace shows red→green but the check is RED right now — the fix regressed".into()
    } else {
        "failure-first satisfied: red→green in an intact trace, currently green".into()
    };

    GateResult { ok, check_digest: digest, trace_intact, saw_red, green_after_red, currently_green, reason }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AcceptanceContract {
    pub check_digest: String,
    pub check_spec: Check,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContractResult {
    pub ok: bool,
    pub action: String,
    pub baseline_digest: String,
    pub current_digest: String,
    pub reason: String,
}

fn contract_result(
    ok: bool,
    action: &str,
    baseline_digest: String,
    current_digest: String,
    reason: impl Into<String>,
) -> ContractResult {
    ContractResult {
        ok,
        action: action.into(),
        baseline_digest,
        current_digest,
        reason: reason.into(),
    }
}

fn validate_check_shape(check: &Check) -> Result<(), String> {
    let exact_one = matches!(
        check.kind,
        CheckKind::FileSha256 | CheckKind::RegexInFile | CheckKind::PromptManifest
    );
    if check.target.is_empty() {
        return Err("check target must not be empty".into());
    }
    if exact_one && check.target.len() != 1 {
        return Err("this check kind requires exactly one target".into());
    }
    if check.target.iter().any(|value| value.is_empty()) {
        return Err("check target values must not be empty".into());
    }
    Ok(())
}

fn effective_check_cwd(workspace: &Path, check: &Check) -> PathBuf {
    let requested = check.cwd.as_deref().map(PathBuf::from);
    let path = match requested {
        Some(path) if path.is_absolute() => path,
        Some(path) => workspace.join(path),
        None => workspace.to_path_buf(),
    };
    path.canonicalize().unwrap_or(path)
}

fn check_in_workspace(workspace: &Path, check: &Check) -> Check {
    let mut resolved = check.clone();
    let effective_cwd = effective_check_cwd(workspace, check);
    resolved.cwd = Some(effective_cwd.to_string_lossy().into_owned());
    if matches!(check.kind, CheckKind::CommandExit) {
        if let Some(program) = resolved.target.first_mut() {
            let candidate = effective_cwd.join(&*program);
            if !Path::new(&*program).is_absolute() && candidate.is_file() {
                *program = candidate
                    .canonicalize()
                    .unwrap_or(candidate)
                    .to_string_lossy()
                    .into_owned();
            }
        }
    }
    resolved
}

fn contract_digest(workspace: &Path, check: &Check) -> String {
    let mut normalized_spec = serde_json::to_value(check).unwrap_or_default();
    let effective_cwd = effective_check_cwd(workspace, check);
    if matches!(check.kind, CheckKind::CommandExit | CheckKind::UiBehavior) {
        if matches!(check.kind, CheckKind::CommandExit) {
            normalized_spec["expect"] =
                serde_json::Value::String(check.expect.as_deref().unwrap_or("0").to_string());
        }
        normalized_spec["cwd"] =
            serde_json::Value::String(effective_cwd.to_string_lossy().into_owned());
    }
    let bind_artifacts =
        matches!(check.kind, CheckKind::CommandExit | CheckKind::UiBehavior);
    let bound_artifacts: Vec<_> = if bind_artifacts {
        check.target.iter().enumerate().filter_map(|(index, argument)| {
            let argument_path = Path::new(argument);
            let path = if argument_path.is_absolute() {
                argument_path.to_path_buf()
            } else {
                effective_cwd.join(argument_path)
            };
            if !path.is_file() {
                return None;
            }
            let resolved = path.canonicalize().unwrap_or(path);
            sha256_file(&resolved).ok().map(|sha256| serde_json::json!({
                "argument_index": index,
                "path": resolved.to_string_lossy(),
                "sha256": sha256,
            }))
        }).collect()
    } else {
        Vec::new()
    };
    let mut canonical_check = check_in_workspace(workspace, check);
    if matches!(check.kind, CheckKind::CommandExit) {
        if let Some(program) = canonical_check.target.first_mut() {
            let program_path = Path::new(program);
            if !program_path.is_absolute() {
                let resolved = effective_cwd.join(program_path);
                *program = resolved
                    .canonicalize()
                    .unwrap_or(resolved)
                    .to_string_lossy()
                    .into_owned();
            }
        }
    }
    let value = serde_json::json!({
        "canonical_digest": canonical_digest(&canonical_check),
        "check_spec": normalized_spec,
        "bound_artifacts": bound_artifacts,
    });
    crate::trace::digest_str(&serde_json::to_string(&value).unwrap_or_default())
}

fn is_reparse(metadata: &std::fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    false
}

struct SafeBaseline {
    workspace: PathBuf,
    relative: PathBuf,
    path: PathBuf,
    parent: PathBuf,
}

impl SafeBaseline {
    fn new(workspace: &Path, baseline: &Path) -> Result<Self, String> {
        if baseline.as_os_str().is_empty() || baseline.is_absolute() {
            return Err("baseline path must be a non-empty relative path".into());
        }
        for component in baseline.components() {
            match component {
                Component::Normal(_) | Component::CurDir => {}
                Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                    return Err("baseline path must not contain parent, root, or prefix components".into());
                }
            }
        }

        let canonical_workspace = workspace
            .canonicalize()
            .map_err(|e| format!("cannot canonicalize workspace: {e}"))?;
        let relative = baseline.to_path_buf();
        let path = canonical_workspace.join(&relative);
        let parent = path.parent().ok_or("baseline path has no parent")?.to_path_buf();
        let safe = Self { workspace: canonical_workspace, relative, path, parent };
        safe.recheck()?;
        Ok(safe)
    }

    fn recheck(&self) -> Result<(), String> {
        // Re-checks guard ordinary path substitution; Phoenix is not a privilege boundary against
        // a malicious same-user process concurrently mutating the workspace.
        let parent_relative = self.relative.parent().unwrap_or_else(|| Path::new(""));
        let mut current = self.workspace.clone();
        for component in parent_relative.components() {
            if let Component::Normal(name) = component {
                current.push(name);
                let metadata = std::fs::symlink_metadata(&current)
                    .map_err(|e| format!("baseline parent must already exist: {e}"))?;
                if is_reparse(&metadata) {
                    return Err("baseline path contains a symlink or reparse point".into());
                }
                if !metadata.is_dir() {
                    return Err("baseline parent component is not a directory".into());
                }
            }
        }
        let canonical_parent = self.parent
            .canonicalize()
            .map_err(|e| format!("cannot canonicalize baseline parent: {e}"))?;
        if !canonical_parent.starts_with(&self.workspace) {
            return Err("baseline parent escapes the workspace".into());
        }
        if let Ok(metadata) = std::fs::symlink_metadata(&self.path) {
            if is_reparse(&metadata) {
                return Err("baseline path is a symlink or reparse point".into());
            }
        }
        Ok(())
    }
}

fn read_contract(workspace: &Path, path: &Path) -> Result<AcceptanceContract, String> {
    let raw = std::fs::read_to_string(path)
        .map_err(|e| format!("cannot read acceptance contract: {e}"))?;
    let contract: AcceptanceContract = serde_json::from_str(&raw)
        .map_err(|e| format!("invalid acceptance contract: {e}"))?;
    validate_check_shape(&contract.check_spec)
        .map_err(|e| format!("stored acceptance contract is invalid: {e}"))?;
    let recomputed = contract_digest(workspace, &contract.check_spec);
    if recomputed != contract.check_digest {
        return Err(
            "stored acceptance contract digest does not match its check_spec or bound artifacts changed"
                .into(),
        );
    }
    Ok(contract)
}

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

fn write_temp(safe: &SafeBaseline, contract: &AcceptanceContract) -> Result<PathBuf, String> {
    let bytes = serde_json::to_vec_pretty(contract)
        .map_err(|e| format!("cannot serialize acceptance contract: {e}"))?;
    for _ in 0..100 {
        let id = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
        let name = format!(".acceptance-contract.{}.{}.tmp", std::process::id(), id);
        let temp = safe.parent.join(name);
        match OpenOptions::new().write(true).create_new(true).open(&temp) {
            Ok(mut file) => {
                let result = file.write_all(&bytes).and_then(|_| file.sync_all());
                if let Err(e) = result {
                    drop(file);
                    let _ = std::fs::remove_file(&temp);
                    return Err(format!("cannot durably write acceptance contract: {e}"));
                }
                return Ok(temp);
            }
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(format!("cannot create contract temp file: {e}")),
        }
    }
    Err("cannot allocate a unique contract temp file".into())
}

#[cfg(unix)]
fn sync_parent(parent: &Path) -> io::Result<()> {
    File::open(parent)?.sync_all()
}

#[cfg(not(unix))]
fn sync_parent(_parent: &Path) -> io::Result<()> {
    Ok(())
}

enum PublishNewError {
    AlreadyExists,
    Other(String),
}

fn publish_new(safe: &SafeBaseline, contract: &AcceptanceContract) -> Result<(), PublishNewError> {
    let temp = write_temp(safe, contract).map_err(PublishNewError::Other)?;
    if let Err(e) = safe.recheck() {
        let _ = std::fs::remove_file(&temp);
        return Err(PublishNewError::Other(e));
    }
    let linked = std::fs::hard_link(&temp, &safe.path);
    if let Err(e) = linked {
        let _ = std::fs::remove_file(&temp);
        return if e.kind() == io::ErrorKind::AlreadyExists {
            Err(PublishNewError::AlreadyExists)
        } else {
            Err(PublishNewError::Other(format!(
                "cannot publish acceptance contract without overwrite: {e}"
            )))
        };
    }
    let result = sync_parent(&safe.parent);
    let _ = std::fs::remove_file(&temp);
    result.map_err(|e| PublishNewError::Other(format!(
        "cannot sync acceptance contract parent: {e}"
    )))
}

#[cfg(unix)]
fn replace_file(temp: &Path, destination: &Path) -> io::Result<()> {
    std::fs::rename(temp, destination)
}

#[cfg(windows)]
fn replace_file(temp: &Path, destination: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;

    #[link(name = "Kernel32")]
    extern "system" {
        fn MoveFileExW(existing: *const u16, new: *const u16, flags: u32) -> i32;
    }

    let existing: Vec<u16> = temp.as_os_str().encode_wide().chain(Some(0)).collect();
    let new: Vec<u16> = destination.as_os_str().encode_wide().chain(Some(0)).collect();
    let moved = unsafe { MoveFileExW(existing.as_ptr(), new.as_ptr(), 0x1 | 0x8) };
    if moved == 0 { Err(io::Error::last_os_error()) } else { Ok(()) }
}

fn publish_replace(safe: &SafeBaseline, contract: &AcceptanceContract) -> Result<(), String> {
    let temp = write_temp(safe, contract)?;
    if let Err(e) = safe.recheck() {
        let _ = std::fs::remove_file(&temp);
        return Err(e);
    }
    if let Err(e) = replace_file(&temp, &safe.path).and_then(|_| sync_parent(&safe.parent)) {
        let _ = std::fs::remove_file(&temp);
        return Err(format!("cannot atomically replace acceptance contract: {e}"));
    }
    Ok(())
}

pub fn freeze_contract(workspace: &Path, baseline: &Path, check: &Check) -> ContractResult {
    let action = "frozen";
    if let Err(reason) = validate_check_shape(check) {
        return contract_result(false, action, String::new(), String::new(), reason);
    }
    let current_digest = contract_digest(workspace, check);
    let safe = match SafeBaseline::new(workspace, baseline) {
        Ok(safe) => safe,
        Err(reason) => return contract_result(false, action, String::new(), current_digest, reason),
    };

    if safe.path.exists() {
        return match read_contract(workspace, &safe.path) {
            Ok(existing) if existing.check_digest == current_digest => contract_result(
                true,
                action,
                existing.check_digest,
                current_digest,
                "acceptance contract already frozen with this check",
            ),
            Ok(existing) => contract_result(
                false,
                action,
                existing.check_digest,
                current_digest,
                "acceptance contract already exists with a changed check",
            ),
            Err(reason) => contract_result(false, action, String::new(), current_digest, reason),
        };
    }
    let sense_result = sense(&check_in_workspace(workspace, check));
    let post_sense_digest = contract_digest(workspace, check);
    if post_sense_digest != current_digest {
        return contract_result(
            false,
            action,
            String::new(),
            post_sense_digest,
            "acceptance check or its bound artifacts changed while sensing",
        );
    }
    if sense_result.ok {
        return contract_result(
            false,
            action,
            String::new(),
            post_sense_digest,
            "acceptance check must be red before it can be frozen",
        );
    }

    let contract =
        AcceptanceContract { check_digest: post_sense_digest.clone(), check_spec: check.clone() };
    match publish_new(&safe, &contract) {
        Ok(()) => contract_result(
            true,
            action,
            post_sense_digest.clone(),
            post_sense_digest,
            "acceptance contract frozen from a red check",
        ),
        Err(PublishNewError::AlreadyExists) => {
            if let Ok(existing) = read_contract(workspace, &safe.path) {
                if existing.check_digest == post_sense_digest {
                    return contract_result(
                        true,
                        action,
                        existing.check_digest,
                        post_sense_digest,
                        "acceptance contract concurrently frozen with this check",
                    );
                }
            }
            contract_result(
                false,
                action,
                String::new(),
                post_sense_digest,
                "acceptance contract was concurrently frozen with a different or invalid check",
            )
        }
        Err(PublishNewError::Other(reason)) => {
            contract_result(false, action, String::new(), post_sense_digest, reason)
        }
    }
}

pub fn validate_contract(workspace: &Path, baseline: &Path, check: &Check) -> ContractResult {
    let action = "validated";
    if let Err(reason) = validate_check_shape(check) {
        return contract_result(false, action, String::new(), String::new(), reason);
    }
    let current_digest = contract_digest(workspace, check);
    let safe = match SafeBaseline::new(workspace, baseline) {
        Ok(safe) => safe,
        Err(reason) => return contract_result(false, action, String::new(), current_digest, reason),
    };
    match read_contract(workspace, &safe.path) {
        Ok(contract) if contract.check_digest == current_digest => contract_result(
            true,
            action,
            contract.check_digest,
            current_digest,
            "acceptance contract matches the current check",
        ),
        Ok(contract) => contract_result(
            false,
            action,
            contract.check_digest,
            current_digest,
            "acceptance check changed from the frozen contract",
        ),
        Err(reason) => contract_result(false, action, String::new(), current_digest, reason),
    }
}

pub fn rescope_contract(workspace: &Path, baseline: &Path, check: &Check) -> ContractResult {
    let action = "rescoped";
    if let Err(reason) = validate_check_shape(check) {
        return contract_result(false, action, String::new(), String::new(), reason);
    }
    let current_digest = contract_digest(workspace, check);
    let safe = match SafeBaseline::new(workspace, baseline) {
        Ok(safe) => safe,
        Err(reason) => return contract_result(false, action, String::new(), current_digest, reason),
    };
    let existing = match read_contract(workspace, &safe.path) {
        Ok(contract) => contract,
        Err(reason) => return contract_result(false, action, String::new(), current_digest, reason),
    };
    let sense_result = sense(&check_in_workspace(workspace, check));
    let post_sense_digest = contract_digest(workspace, check);
    if post_sense_digest != current_digest {
        return contract_result(
            false,
            action,
            existing.check_digest,
            post_sense_digest,
            "rescoped acceptance check or its bound artifacts changed while sensing",
        );
    }
    if sense_result.ok {
        return contract_result(
            false,
            action,
            existing.check_digest,
            post_sense_digest,
            "rescoped acceptance check must be red",
        );
    }

    let contract =
        AcceptanceContract { check_digest: post_sense_digest.clone(), check_spec: check.clone() };
    match publish_replace(&safe, &contract) {
        Ok(()) => contract_result(
            true,
            action,
            post_sense_digest.clone(),
            post_sense_digest,
            "acceptance contract explicitly rescoped to a red check",
        ),
        Err(reason) => {
            contract_result(false, action, existing.check_digest, post_sense_digest, reason)
        }
    }
}
