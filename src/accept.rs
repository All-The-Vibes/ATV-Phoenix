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

use crate::sense::{canonical_digest, sense, Check};
use crate::trace::Trace;
use serde::{Deserialize, Serialize};
use std::path::Path;

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
