# phoenix-ralph — the loop driver

Geoffrey Huntley's Ralph loop (`while :; do cat PROMPT.md | agent; done`,
[ghuntley.com/ralph](https://ghuntley.com/ralph)), **Phoenix-gated**: the driver proves completion
objectively instead of trusting the agent to say "done."

## When to use this driver (vs the interactive loop)

There are **two ways** to run `phoenix-ralph`:

- **Interactive (inside the Copilot CLI):** just invoke `/phoenix-ralph` in your session — no script.
  The loop runs in-session as the agent's own tool-use loop, and it proves completion with the
  **`phoenix_accept` MCP tool**. That's the common case.
- **This driver (unattended / large jobs):** for overnight runs, CI, or work too big for one context
  window. `copilot -p` and Scout are **one-shot** — no "re-inject the prompt" hook — so this external
  script *is* the persistence, giving Huntley's **fresh context every iteration**. It calls
  `phoenix-mcp accept` (the CLI form of the same gate).

Both share one law: **the gate proves completion** (red→green on an intact trace), never self-report.

## What makes it Phoenix (not just a `while` loop)

The single most important rule: **the driver decides completion, the agent only proposes it.** The
loop stops only when `phoenix-mcp accept done-check.json` proves the goal is **failure-first
satisfied** — the tamper-evident trace shows the check went **red → green** for the *same* check, the
chain is intact, and it is **green right now**. A check that was never seen failing (a vacuous
`test -f`) is rejected. An agent that dishonestly marks work done can't fake the trace.

```
            ┌──────────────────────────────────────────────┐
            │  driver: accept(done-check)?  ── green ──▶ DONE │ (writes completed.json + git tag)
            └───────────────┬──────────────────────────────┘
                            │ red / unproven
                            ▼
              copilot -p PROMPT.md   (fresh context, one task)
                            │
              verify-trace intact?  ── broken ──▶ STOP (tamper)
                            │ ok
              state changed?  ── no, N times ──▶ STOP (stuck)
                            │ yes
                            └────────────── loop ◀───────────
```

## Use

```powershell
# 1. scaffold state in your repo
mkdir .phoenix-ralph
copy dist\ralph\PROMPT.template.md   .phoenix-ralph\PROMPT.md
copy dist\ralph\backlog.example.json .phoenix-ralph\backlog.json     # edit to your work items
copy dist\ralph\done-check.example.json .phoenix-ralph\done-check.json  # the real acceptance test

# 2. run the loop (Phoenix MCP must be registered / binary built)
powershell -ExecutionPolicy Bypass -File dist\ralph\phoenix-ralph.ps1 -MaxLoops 30
```

```bash
# bash twin (Scout-on-WSL / Linux / macOS)
MAX_LOOPS=30 bash dist/ralph/phoenix-ralph.sh
```

### The contract for `done-check.json`
- Must be a real `command_exit` (a test/build that actually exercises the goal), **not** a
  `regex_in_file`/`file_sha256` (those are fine as per-item sub-checks, weak as the final gate).
- Must start **RED**. The driver refuses an already-green done-check (pass `-AllowPreGreen` only if
  it's legitimately already satisfied) — a gate that can't fail proves nothing.
- **Avoid vacuous gates.** A bare `npm test`, `pnpm build`, or empty `pytest` on a fresh scaffold
  exits 0 before any feature exists — the driver will (correctly) reject it as already-green. Gate on
  **content**: run a specific named test (e.g. `pytest tests/test_acceptance.py::test_goal_complete`),
  or a verify script that checks the built artifact for expected output. The example in
  `done-check.example.json` demonstrates this pattern.

### Guardrails the driver owns
`-MaxLoops`, `-MaxMinutes` (wall-clock), `-NoProgressStop` (stop after N loops with no trace/backlog
change), trace-intact check every iteration, and the proof bundle + git tag on success. The agent
never writes `completed.json` or tags — only the driver does, and only on a proven `accept`.

See [`docs/autonomous-workflows.md`](../../docs/autonomous-workflows.md) for the full design and the
research it's grounded in ([`research/autonomous-workflows-research.md`](../../research/autonomous-workflows-research.md)).
