# ATV-Phoenix

**A self-healing harness for AI coding agents.** Phoenix gives GitHub Copilot (and Microsoft Scout)
the one organ they're missing: the ability to **objectively sense when a task actually failed, and
heal it** — instead of declaring "done" on silently-broken work.

> _Rises from its own ashes. Senses when it's broken, heals itself, gets better with use._

---

## The result that justifies it

On **20 live GitHub Copilot sessions**, with vs. without Phoenix, scored by hidden acceptance checkers:

| | Vanilla Copilot | Copilot + Phoenix |
|---|---|---|
| Well-specified tasks | 6/6 pass | 6/6 pass *(no regression)* |
| **Underspecified tasks** (hidden acceptance criteria) | **0/4 pass — 4 silent failures** | **4/4 pass — 0 silent failures** |
| **Silent-failure rate** | **40%** | **0%** |

**Vanilla Copilot shipped broken code with false confidence; Phoenix caught and healed every case** —
with zero regressions on tasks the model already gets right. Full method + raw data:
[`evals/h2-experiment/`](evals/h2-experiment/RESULT.md).

---

## What Phoenix gives the agent (4 tools)

| Tool | What it does |
|---|---|
| `phoenix_sense` | Objectively check success — a command's exit code, a file hash, or a regex. **No self-grading.** |
| `phoenix_snapshot` | Save a known-good state — but **only if a check passes** (never blesses broken state). |
| `phoenix_heal` | Bounded recovery (rollback to a snapshot, or retry ≤3×), **confirmed by an external recheck**. |
| `phoenix_verify_trace` | Audit a tamper-evident, hash-chained trace of everything sensed and healed. |

The loop: **baseline-green → snapshot → edit → sense → heal if red → confirm green** — all on
*objective* signals, all traced.

---

## Install

### GitHub Copilot CLI (MCP server)
Register the Phoenix MCP server, then it's available in any session:
```powershell
git clone https://github.com/All-The-Vibes/ATV-Phoenix
cd ATV-Phoenix
./dist/install.ps1          # builds the release binary + installs the Copilot agent
```
Phoenix registers as an MCP server (`~/.copilot/mcp-config.json`) exposing the four tools.
Ask Copilot to verify + heal a task and it calls them. (See [`dist/`](dist/) for details.)

### Microsoft Scout (CLI adapter)
Scout doesn't take external MCP servers, so Phoenix ships a **CLI** the Scout agent calls via its
shell tool, plus a Scout skill that teaches the verify-heal loop:
```powershell
phoenix-mcp sense   '{"kind":"command_exit","target":["pytest","-q"],"expect":0}'   # exit 0 = pass
phoenix-mcp snapshot src/app.py '{"kind":"command_exit","target":["pytest","-q"]}'
phoenix-mcp heal    rollback '{"path":"src/app.py","snap_id":"...","recheck":{...}}'
phoenix-mcp verify-trace
```
See [`dist/scout/`](dist/scout/). Same Rust binary, both hosts.

---

## Why it works (the thesis)

**The orchestration layer — not the model — determines agent success.** Most "the model failed"
problems are *harness* failures: no objective completion signal, no recovery, no evidence. Phoenix is
the missing layer. Two design principles it proves:

- **Enforce, don't offer.** In the experiment, unprompted Copilot self-verified **0/10** times. Value
  comes from the harness *enforcing* the verify-heal loop, not from a tool merely being available.
- **Evidence over self-grading.** `phoenix_sense` only reports objective signals; "I'm not sure it
  passed" is allowed, a fabricated "done!" is the failure mode Phoenix exists to prevent.

Phoenix composes proven parts ([TokenMasterX](https://github.com/shyamsridhar123/TokenMasterX) for
token-efficient retrieval; [agentskills.io](https://agentskills.io) skills) and builds only the novel
spine: **objective sensing, bounded healing, measured improvement.**

---

## Status (v0.1.0)

| Milestone | Proven | Evidence |
|---|---|---|
| M1 | self-healing spine (Rust) | `cargo test` + [screenshot](evals/screenshots/m1-self-heal.png) |
| M2 | works over real MCP | [screenshot](evals/screenshots/m2-mcp-session.png) |
| M3 | heals live inside Copilot | [screenshot](evals/screenshots/m3-live-copilot.png) |
| H2 | 40%→0% silent failures | [screenshot](evals/screenshots/h2-results.png) |

**Honest limits:** results are directional (small n, single model, deterministic checkers). Recovery is
"bounded objective recovery," not broad self-healing. Command timeouts aren't yet enforced in-process.
See [`BUILDLOG.md`](BUILDLOG.md) for the full honest engineering record — every bug, reversal, and dead end.

## License
MIT — see [LICENSE](LICENSE). Composes MIT/open components (TokenMasterX, agentskills.io packs) with attribution.
