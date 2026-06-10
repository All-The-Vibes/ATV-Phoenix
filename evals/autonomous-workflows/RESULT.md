# Autonomous workflows — gate ledger + Ralph driver (eval)

**Date:** 2026-06-10 · **What:** the failure-first gate ledger (`phoenix-mcp accept`) and the Ralph
loop driver that proves completion objectively. Evidence that "done" is derived from the tamper-evident
trace, not self-reported.

## 1. Gate ledger unit tests (`tests/gate_ledger.rs`) — 3/3 pass

| Test | Asserts | Result |
|---|---|---|
| `accepts_failure_first_red_then_green` | a check seen RED then GREEN, green now, intact trace → **accept** | PASS |
| `rejects_vacuous_never_red_check` | a check green now but **never seen red** → **reject** (vacuous-gate guard) | PASS |
| `rejects_tampered_trace` | flipping a recorded `ok:false`→`true` in the JSONL → **reject** (chain broken) | PASS |

Full suite: `cargo test --release` → gate_ledger 3/3, m1_self_heal 3/3, m2_mcp_session 1/1,
skills_doctor 2/2 (16/16 skills), lib 2/2. All green.

## 2. CLI gate ledger (`phoenix-mcp accept`) — proven via the binary

```
# vacuous: check is green NOW but the trace never saw it red  -> REJECTED (exit 1)
$ phoenix-mcp accept @done-check.json
{"ok":false,"saw_red":false,"currently_green":true,
 "reason":"no RED observation for this check in the trace — a gate never seen failing proves
  nothing (vacuous-check guard). Reproduce the failure first, then fix it."}

# failure-first: trace shows red then green, green now  -> ACCEPTED (exit 0)
$ phoenix-mcp accept @done-check.json
{"ok":true,"saw_red":true,"green_after_red":true,"currently_green":true,
 "reason":"failure-first satisfied: red→green in an intact trace, currently green"}
```

## 3. Ralph driver (`dist/ralph/phoenix-ralph.ps1`) — both paths, no real Copilot calls

**Case A — vacuous top-level gate refused.** A `done-check` that is already green at startup:
```
[ralph] baseline sense of done-check...
[ralph] FATAL: done-check is ALREADY GREEN at start -- it can't prove failure-first (it'd be a
        vacuous gate). Re-target the check at the real unmet goal, or pass -AllowPreGreen ...
driver exit=2
```

**Case B — happy path.** A `done-check` that starts RED; a stubbed agent turn makes it green:
```
[ralph] iteration 1/5 -- invoking agent (fresh context)...
[ralph] done-check ACCEPTED (failure-first, green). Goal proven complete.
[ralph] COMPLETE in 2 iterations. Proof -> .phoenix-ralph\completed.json
[ralph] git tag: phoenix-ralph-20260610-151719
driver exit=0
```
Driver-written `completed.json` proof bundle:
```json
{ "iterations": 2,
  "accept": { "ok": true, "saw_red": true, "green_after_red": true, "currently_green": true,
              "reason": "failure-first satisfied: red->green in an intact trace, currently green" },
  "trace_sha256": "4967F52C...", "backlog_sha256": "absent" }
```

## What this proves
- Completion is **derived from the trace by the driver**, not authored by the agent.
- A check that was **never observed failing is rejected** — the vacuous-gate guard works at both the
  ledger (CLI) and driver levels.
- A **tampered trace breaks acceptance** — dishonest "done" is caught, not just theoretically catchable.
- The external loop driver runs Huntley's fresh-context loop on a one-shot host (Copilot/Scout), owns
  all budgets/guardrails, and writes the proof bundle + git tag only on a proven `accept`.

## Honest limits
- `accept` proves *a check* went red->green; it is only as strong as the check (hence the
  `command_exit`-for-top-level-gate and failure-first rules). Garbage check in, garbage proof out.
- The driver controls cost via budgets (`-MaxLoops`/`-MaxMinutes`/`-NoProgressStop`), not a hard sandbox.
- A live end-to-end Copilot run (real agent building a project under the loop) is the next evidence
  step; this eval proves the spine + driver mechanics with a stubbed agent to keep it deterministic and
  free.

## Artifacts
`src/accept.rs` (gate ledger), `tests/gate_ledger.rs`, `dist/ralph/` (driver + templates),
`skills/phoenix-ralph|phoenix-goal|phoenix-auto`, `docs/autonomous-workflows.md`,
`research/autonomous-workflows-research.md` (sourced research).
