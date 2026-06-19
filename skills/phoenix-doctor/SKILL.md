---
type: Phoenix Skill
name: phoenix-doctor
description: Diagnose and repair a Phoenix install with the same objective discipline Phoenix gives the agent — check whether the installed agent, skills, and MCP registration match what this build ships, and re-sync any drift with a snapshot-backed fix that is re-verified red→green. Use when Copilot says "No such agent: phoenix", a skill is missing or behaving oddly, after upgrading Phoenix, or when the user says /phoenix-doctor, "doctor", "diagnose my install", "repair phoenix", or "is phoenix installed right".
license: MIT
---

# phoenix-doctor — verify the install, then heal it

## Overview
Phoenix is a self-healing harness; `phoenix-doctor` points that discipline at **Phoenix's own install**.
It compares the *installed* agent, skills, and MCP registration against what THIS build ships (embedded
in the `phoenix-mcp` binary), reports any drift with objective evidence, and `--fix` re-syncs from the
shipped reference — then re-runs the same check so a repair only counts when it goes **red→green**. It also
checks the running binary itself is built from the current source, so it can't be fooled by its own truth
being out of date. This
is the antidote to the whole class of "I installed it a while ago and something's off" problems: you never
guess, you compare to the source of truth.

## When to use
- `copilot --agent phoenix` says **"No such agent: phoenix"** (or it's missing from the list).
- A `/phoenix-*` skill is missing, stale, or behaving differently than the docs say.
- Right after **upgrading / re-pulling** Phoenix, to confirm the install matches the new build.
- Any "is my install healthy?" question.

## How to run it

**1. Diagnose (cheap, offline — no auth, no model):**
```
phoenix-mcp doctor
```
Prints a JSON `InstallReport` plus a human summary, and exits non-zero if anything is wrong. Each check is
shaped like a `phoenix_sense` result — `{check, ok, evidence, problems}` — so the signal is objective.

**2. Repair (idempotent, snapshot-backed):**
```
phoenix-mcp doctor --fix
```
Re-syncs the agent + any missing/drifted skills from the shipped reference and re-registers the MCP server,
backing up the prior agent/mcp-config as `*.doctor-bak` first, then re-verifies. Safe to re-run; a clean
install is a no-op.

**3. Authoritative load test (`--deep`, needs the CLI + auth):**
The drift check tells you the file matches the source of truth; the load test proves the CLI actually
*accepts* it. After a fix, confirm with the real loader:
```
copilot --agent phoenix -p "reply READY" -s --allow-all-tools
```
"No such agent" (red) → "READY" (green) is the end-to-end proof the repair worked. Run this against the
same home you fixed (`--home`/`$COPILOT_HOME` if non-default).

Use `--home <dir>` to target a non-default Copilot home (default: `$COPILOT_HOME` or `~/.copilot`).

## What it checks
| Check | Green means | Caught the real bug? |
|---|---|---|
| **agent** | `agents/phoenix.agent.md` is present and matches the shipped template (path-independent) | ✅ the missing-`args` agent that wouldn't load — caught generically as drift, not a hardcoded field |
| **skills** | every shipped `/phoenix-*` skill is installed and byte-matches its shipped copy | ✅ missing/stale skills after an upgrade |
| **mcp-config** | the `phoenix` MCP server is registered and its binary resolves on disk | ✅ unregistered or moved binary |
| **build** | the running `phoenix-mcp` was built from the repo's current `HEAD` (the binary *is* the source of truth the other checks compare against — this proves that truth isn't itself stale) | ✅ a binary built before recent commits, which would otherwise pass install as "healthy" against an out-of-date reference |

## Rules
- **Compare, don't guess.** Health is "matches what this build ships", measured by hash — not by reading
  the file and deciding it looks fine. The shipped reference is embedded in the binary; that's the truth.
- **Generic over specific.** The drift check has no per-field knowledge (it does not look for `args` or any
  one key). That's deliberate: it catches the *next* schema bug too, and never goes stale.
- **A fix is real only when re-verified.** `--fix` re-runs the check after writing; for the agent, finish
  with the `--deep` load test. Red→green, or it isn't fixed.
- **Reversible.** The prior agent + mcp-config are saved as `*.doctor-bak` before any overwrite.
- **Staleness needs a rebuild, not `--fix`.** `--fix` re-syncs the install *to* the binary; it cannot help
  when the binary itself is `behind` the repo. Fix that with `cargo build --release`, then re-run `doctor`.

## Common Rationalizations
| Rationalization | Reality |
|---|---|
| "The file is there, so the install is fine." | Present ≠ valid. The missing-`args` agent existed on disk and still wouldn't load. Compare to shipped + run the load test. |
| "I'll just hand-edit the broken line." | That fixes one symptom on one machine. `doctor --fix` re-syncs to the source of truth and stays correct on the next upgrade. |
| "Drift detection is overkill — just check the agent loads." | The load test needs auth and a model call; the offline drift check is the cheap first pass and pinpoints *what* drifted. Use both, in that order. |
| "It says fixed, so it's fixed." | Only if the re-check is green. For the agent, "fixed" means `copilot --agent phoenix` returns, not that a file was written. |

## Red Flags
- "No such agent: phoenix" → `phoenix-mcp doctor` then `--fix`, then the `--deep` load test.
- Editing `~/.copilot/agents/phoenix.agent.md` by hand → prefer `--fix`; hand-edits are the drift this skill detects.
- A skill behaving unlike its docs after an upgrade → it's probably stale; `doctor` will flag it, `--fix` re-syncs.
- Reporting "repaired" with no load test → run `copilot --agent phoenix` to confirm green.
- `build: behind` → your `phoenix-mcp` is older than the repo source; rebuild with `cargo build --release`
  (`--fix` can't repair this), then re-run `doctor`.

## Next
Once the install is green, get to work: `/phoenix` to route a task, or jump straight to
`phoenix-think → plan → build`. If `doctor --fix` can't reach green, the binary itself may be missing or
unbuilt — re-run the installer (`setup.py`), which builds `phoenix-mcp` and re-registers everything.
