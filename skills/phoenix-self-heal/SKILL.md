---
name: phoenix-self-heal
description: Verify-then-heal loop for any code change with a checkable outcome. Use the Phoenix tools (phoenix_sense, phoenix_snapshot, phoenix_heal, phoenix_verify_trace) to OBJECTIVELY confirm a task succeeded — a command's exit code, a file hash, or a regex — and to recover (rollback to a known-good snapshot, or retry) when it failed, instead of self-judging. Trigger whenever you edit code that has a runnable test/build/lint, or whenever success must be verified rather than assumed.
license: MIT
---

# phoenix-self-heal

A portable [agentskills.io](https://agentskills.io) skill that drives the ATV-Phoenix verify-heal loop.
Works with any host that exposes the Phoenix tools (GitHub Copilot via MCP, or the `phoenix-mcp` CLI).

## The tools
- **phoenix_sense(check)** — objective check. `check.kind` ∈ `command_exit` (run argv, pass iff exit
  code == expect, default 0), `file_sha256`, `regex_in_file`. Returns `{ok, signal, evidence}`. No self-grading.
- **phoenix_snapshot(path, check)** — save `path` as last-good, **only if `check` passes**. Returns `{blessed, snap_id}`.
- **phoenix_heal(strategy, ctx)** — bounded recovery (`rollback` to a snapshot, or `retry` ≤3×),
  confirmed by an **external** recheck. Returns `{healed, attempts}`.
- **phoenix_verify_trace()** — audit the tamper-evident, hash-chained trace.

## Example call (sense)
```json
{"check":{"kind":"command_exit","target":["pytest","-q"],"expect":0}}
```
`target` accepts an argv array (preferred) or a single command string; `expect` accepts an integer or string.

## The loop (follow it for any checkable change)
1. **Baseline green:** `phoenix_sense` the project's test/build command.
2. **Snapshot:** `phoenix_snapshot` the file(s) you will edit (only blesses if green).
3. **Edit.**
4. **Re-sense:** `phoenix_sense` again. If `ok` is false, you broke it.
5. **Heal:** `phoenix_heal` (rollback to the snapshot, or retry). Trust the **external recheck**, not your judgment.
6. **Evidence:** optionally `phoenix_verify_trace` to show objective proof of what happened.

## Honesty
Never claim success you didn't `phoenix_sense`. "I'm not sure it passed" is acceptable; a fabricated
"done" is exactly the failure mode this skill exists to prevent. Recovery is real only when the
external recheck is green.
