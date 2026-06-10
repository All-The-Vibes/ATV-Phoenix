//! ATV-Phoenix spine — objective sensing, bounded recovery, blessed snapshots, tamper-evident trace.
//!
//! This is the ONE novel thing Phoenix adds on top of GitHub Copilot + TokenMasterX: the ability to
//! SENSE objective failure and HEAL it within bounded, logged, reversible actions. No LLM here — only
//! objective signals (exit codes, hashes, regex). See docs/v0-spine-design.md.

pub mod sense;
pub mod snapshot;
pub mod heal;
pub mod trace;
pub mod doctor;
pub mod accept;

pub use doctor::{doctor, DoctorReport};
pub use heal::{heal, HealCtx, HealResult, Strategy};
pub use sense::{sense, Check, CheckKind, SenseResult};
pub use snapshot::{snapshot, SnapshotResult};
pub use trace::{Trace, TraceVerify};
pub use accept::{verify_gate, GateResult};
