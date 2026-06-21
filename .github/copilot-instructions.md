# Copilot instructions — ATV-Phoenix

**Read [`AGENTS.md`](../AGENTS.md) first. It is the binding build charter and it governs all work here.**

Short version: **Phoenix builds Phoenix.** Every change to the lights-out-factory connectors goes through
Phoenix's own loop — **FORMALIZE** a runnable `phoenix_sense` acceptance check *before* code, work in small
steps, **snapshot** before risky edits, **sense** every step (binary green/red, never self-judge), **heal**
on red (never advance), and treat a task as **done only when `phoenix_accept` proves a check went
red → green** (never self-report). Ship via PR with the trace attached; human gate on risky changes; never
direct-commit. Promote verified outcomes into the OKF / Phoenix's-Nest bundle.

A connector without a formalized acceptance check is **not ready to start.** A connector PR without a
`phoenix_accept` (red→green) trace is **not mergeable.**

Use the TokenMasterX code graph (`graphify-nav/*`) for structural questions instead of grep-and-reread.

See `AGENTS.md` for the 3 connectors, their acceptance checks, and the architecture rules.
