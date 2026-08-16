//! `run_artifacts` — the structured record of what a dispatched job actually produced.
//!
//! [`crate::cloud_backend`] currently reports its result as a formatted `detail` string. That is fine
//! for a human reading a log and useless for the run ledger #80 calls for, which has to persist task
//! IDs, backend decisions, model, usage, and errors as *fields*. Re-parsing prose to recover them
//! would be a data-integrity bug waiting to happen: the moment the wording changes, the ledger
//! silently starts recording nothing.
//!
//! So the facts live here as typed values, built once at the point where they are known. The prose
//! stays as a human-facing summary derived *from* the record, never the other way round.
//!
//! Everything is optional except the backend name, because a backend that fails before dispatch
//! genuinely has no task id and no usage — and inventing a zero would make "we never asked" and
//! "it cost nothing" indistinguishable in the ledger.
//!
//! INVARIANT: absent and zero stay distinct. Every field a pre-dispatch failure cannot know is
//! `Option`, so "we never asked" and "it cost nothing" never collapse into the same ledger row.
//! INVARIANT: the human-facing summary is derived from the typed record, never parsed back out of
//! it. Re-parsing prose to recover fields means the ledger silently records nothing the moment the
//! wording changes.

/// Token and cost accounting reported by a backend, when it reports any.
///
/// Fields are individually optional: a backend may know token counts but not cost, or neither.
/// `None` means "not reported", which is a different fact from `Some(0)`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Usage {
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    /// Cost in the smallest currency unit, avoiding float rounding in a ledger.
    pub cost_micros: Option<u64>,
}

impl Usage {
    /// Usage where nothing was reported.
    pub fn unreported() -> Self {
        Self::default()
    }

    pub fn with_tokens(input: u64, output: u64) -> Self {
        Self { input_tokens: Some(input), output_tokens: Some(output), cost_micros: None }
    }

    pub fn with_cost(mut self, cost_micros: u64) -> Self {
        self.cost_micros = Some(cost_micros);
        self
    }

    /// Whether the backend reported anything at all.
    pub fn is_reported(&self) -> bool {
        self.input_tokens.is_some() || self.output_tokens.is_some() || self.cost_micros.is_some()
    }

    /// Total tokens, only when both halves were reported.
    ///
    /// Returns `None` rather than treating a missing half as zero — a half-known total is a
    /// fabricated number, and the ledger must not carry one.
    pub fn total_tokens(&self) -> Option<u64> {
        match (self.input_tokens, self.output_tokens) {
            (Some(i), Some(o)) => Some(i.saturating_add(o)),
            _ => None,
        }
    }
}

/// What a run produced and what it cost — the ledger-facing record of one dispatch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunArtifacts {
    /// Which backend produced this. Always known.
    pub backend: String,
    /// Remote task identifier, when the job was actually dispatched.
    pub task_id: Option<String>,
    /// Branch the work landed on, when it produced one.
    pub branch: Option<String>,
    /// Model the backend used, when it reported one.
    pub model: Option<String>,
    pub usage: Usage,
    /// Failure reason, when the run did not succeed.
    pub error: Option<String>,
}

impl RunArtifacts {
    /// A record for a run that never reached a backend's remote at all.
    pub fn none_for(backend: impl Into<String>) -> Self {
        Self {
            backend: backend.into(),
            task_id: None,
            branch: None,
            model: None,
            usage: Usage::unreported(),
            error: None,
        }
    }

    pub fn with_task_id(mut self, task_id: impl Into<String>) -> Self {
        self.task_id = Some(task_id.into());
        self
    }

    pub fn with_branch(mut self, branch: impl Into<String>) -> Self {
        self.branch = Some(branch.into());
        self
    }

    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = Some(model.into());
        self
    }

    pub fn with_usage(mut self, usage: Usage) -> Self {
        self.usage = usage;
        self
    }

    pub fn with_error(mut self, error: impl Into<String>) -> Self {
        self.error = Some(error.into());
        self
    }

    /// Whether the job was dispatched far enough to receive a task id.
    pub fn was_dispatched(&self) -> bool {
        self.task_id.is_some()
    }

    /// A stable, human-facing one-line summary derived from the fields.
    ///
    /// This is the *output* of the record, never its source. Callers that need a fact read the
    /// field; only logs read this.
    pub fn summary(&self) -> String {
        let mut parts = vec![format!("backend={}", self.backend)];
        if let Some(task) = &self.task_id {
            parts.push(format!("task={task}"));
        }
        if let Some(branch) = &self.branch {
            parts.push(format!("branch={branch}"));
        }
        if let Some(model) = &self.model {
            parts.push(format!("model={model}"));
        }
        if let Some(total) = self.usage.total_tokens() {
            parts.push(format!("tokens={total}"));
        }
        if let Some(cost) = self.usage.cost_micros {
            parts.push(format!("cost_micros={cost}"));
        }
        if let Some(err) = &self.error {
            parts.push(format!("error={err}"));
        }
        parts.join(" ")
    }
}
