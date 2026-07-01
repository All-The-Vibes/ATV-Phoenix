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

**Also add a negative/absence assertion** — prove the legacy thing is *gone*, not just
the new thing present. Positive-only gates are a documented source of premature
completion (see issue #13). Copy `dist/ralph/surface-scan-template.mjs`, configure its
`forbiddenPatterns` list, and add it as a second done-check step: start RED (offenders
listed at `file:line`), green when the surface is clean.

### Guardrails the driver owns
`-MaxLoops`, `-MaxMinutes` (wall-clock), `-NoProgressStop` (stop after N loops with no trace/backlog
change), trace-intact check every iteration, and the proof bundle + git tag on success. The agent
never writes `completed.json` or tags — only the driver does, and only on a proven `accept`.

See [`docs/autonomous-workflows.md`](../../docs/autonomous-workflows.md) for the full design and the
research it's grounded in ([`research/autonomous-workflows-research.md`](../../research/autonomous-workflows-research.md)).

## Live/serve gate rules (Windows — issue #12)

Two gotchas that produce false results on Windows when the gate spawns a long-lived
serve process (e.g. `next start`, `pnpm start`):

### Rule 1 — Never `stdio:'inherit'` for serve processes

```js
// WRONG — hangs sense for ~14 min; leaks server processes each iteration
spawn('pnpm', ['start'], { stdio: 'inherit' })

// CORRECT — sense always returns; server tree is isolated
spawn('pnpm', ['start'], { stdio: 'ignore', windowsHide: true })
```

`stdio:'inherit'` lets the served tree inherit the sense process's stdout/stderr
pipe. On Windows, detached grandchildren (pnpm → cmd → next) survive
`taskkill /T /F` of the parent and keep the inherited pipe open.
`phoenix-mcp sense` reads the child pipe to EOF — it blocks until the driver's
coarse timeout (~14 min observed, 864838ms), leaking a listening server each
iteration.

**Also kill by port** in teardown — pid-tree kill alone misses the detached grandchild:

```js
// After killing serveProc, also:
// netstat -ano | findstr :3000 → taskkill /PID <pid> /T /F
```

A template with both fixes is at `dist/ralph/live-gate-template.mjs`.

### Rule 2 — Case-insensitive `innerText` matching

```js
// WRONG — false-RED when CSS text-transform:uppercase is applied
document.body.innerText.includes('Next Best Offer')   // → false if rendered as "NEXT BEST OFFER"

// CORRECT — matches regardless of CSS letter-case transform
bodyText.toLowerCase().includes(marker.toLowerCase())
```

`innerText` returns text with CSS `text-transform` applied. Any design system that
uppercases headings/eyebrows produces false-RED on content that IS present. This
pressures an autonomous agent to remove the uppercase styling to satisfy the gate —
the mirror image of the anti-pattern Phoenix is built to prevent.
