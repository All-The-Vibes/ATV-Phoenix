# ATV-Phoenix x OKF — community demo

A single, self-contained, **runnable** demo that tells the whole Open Knowledge Format story on
real artifacts, through the real Phoenix spine. Built to be shown live or recorded.

```powershell
pwsh demo/okf/run-demo.ps1            # interactive: pauses between beats
pwsh demo/okf/run-demo.ps1 -NoPause   # straight through (for recording)
```

> Non-destructive: everything happens in `demo/okf/.work/` (gitignored). Deterministic: **no model
> is called** — every "green" is an exit code, every number is `tiktoken`. Nothing to fake.

## What it needs

- `python` on PATH with `pyyaml` (and `tiktoken` only if you also run the evals).
- A built spine binary at `target/release/phoenix-mcp.exe` (or `target/debug/…`). Build with
  `cargo build --release` if missing.
- Optional: a live `.token-master/graph.json`. If absent, Beat 1 falls back to the committed
  `examples/okf-code-graph/` bundle — the demo still runs fully.

## The five beats (≈3 minutes)

| Beat | What the audience sees | The point |
|---|---|---|
| **1 PRODUCE** | `graph.json` (an opaque 90k-token blob) becomes 50 markdown concept docs you can `cat` and `git diff`. | Knowledge leaves the black box. |
| **2 VALIDATE** | `okf_validate` prints `CONFORMANT … (exit 0)`. | That exit code **is** a `phoenix_sense` gate — knowledge has an objective pass/fail. |
| **3 SENSE + HEAL** | Through the **real `phoenix-mcp.exe`**: sense GREEN → strip a concept's `type` → sense **RED** → `heal rollback` → sense GREEN → `accept` (`ok=true`) → `verify-trace`. | A knowledge bundle that drifts emits a RED a run can **heal**, proven red→green in a tamper-evident trace. Same discipline Phoenix gives code. |
| **4 CONSUME** | `okf_ingest` shows the index-first outline, then opens **exactly one** concept to answer a real structural question. | Pay once to orient, then never again. 31.3× fewer tokens than dumping `graph.json`. |
| **5 INTEROP** | A **foreign**, hand-authored bundle (`Runbook`/`Dataset`/`Decision`/`Glossary`) validates and ingests with zero changes. | OKF is vendor-neutral — and so is Phoenix. It consumes anyone's bundle. |

## Talking track (one line per beat)

1. "This is Phoenix's code knowledge today — a JSON blob no human reads. Watch it become a folder of markdown."
2. "Now it has a gate. Conformance is an exit code, not a vibe."
3. "Here's the Phoenix move: I'll break the knowledge on purpose. The spine catches it RED, heals it by rollback, and **proves** the red→green in a hash-chained trace. Knowledge is a self-healing artifact."
4. "Reading it back: I don't dump the folder, I orient once and open exactly what I need — 31× cheaper than the blob."
5. "And it's not just *our* format — here's a bundle we never produced, with a totally different vocabulary. Same tools, zero changes."

Close: **"Phoenix produces open knowledge, gates it, senses and heals it like code, consumes it
cheaply, and interops with anyone's OKF bundle. Knowledge is now a first-class, self-healing,
vendor-neutral artifact — not an opaque blob."**

## Where the receipts live

- Token numbers: [`evals/m4-okf/RESULT.md`](../../evals/m4-okf/RESULT.md) (produce/measure) and
  [`evals/m5-okf-live/RESULT.md`](../../evals/m5-okf-live/RESULT.md) (a live phoenix-context run).
- The skill itself: [`skills/phoenix-okf/`](../../skills/phoenix-okf/) (export / validate / freshness
  / ingest + committed sense recipes).
- Conformance enforced in CI: [`.github/workflows/okf.yml`](../../.github/workflows/okf.yml) and the
  test suite in [`tests/okf/`](../../tests/okf/) + the spine sense test
  [`tests/okf_sense.rs`](../../tests/okf_sense.rs).
