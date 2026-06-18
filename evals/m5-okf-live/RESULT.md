# M5 — OKF consumed in a live phoenix-context run

**Goal:** prove the OKF consumer (`okf_ingest`) is not a stand-alone toy — that it answers a real
**phoenix-context** structural question end to end, on the committed bundle, with real captured
output and honest token accounting.

## What ran

`evals/m5-okf-live/run_okf_live.py` runs the phoenix-context loop for real against the committed
`examples/okf-code-graph/` bundle. It invokes `okf_ingest` as a **subprocess** at each step (nothing
is mocked) and counts tokens with tiktoken `o200k_base`.

**Question (a genuine "what does X relate to" structural question):**
> What cross-file (candidate) edges does `src/heal.rs` have, and what symbols does it define?

**phoenix-context routing decision:** structural question → go to the prebuilt knowledge artifact,
do **not** grep-and-read. The loop then progressively discloses:

| Turn | Action | Cost |
|---|---|---|
| 1 | `okf_ingest` index-first outline (types, tags, 50 concepts) — paid **once** per session | 2,470 tok |
| 2 | `okf_ingest --query Rust` — locate the concept, **no file reads** | 541 tok |
| 3 | `okf_ingest --full concepts/src/heal.rs.md` — open **exactly one** concept | 403 tok |

The answer is read straight off the concept's frontmatter (`7 symbols`) and its **Relationships**
section (3 cross-file `candidate` edges: `heal_rollback()`/`heal_retry()` → `sense()`,
`heal_rollback()` → `restore()`), with every INFERRED edge flagged `candidate` per the
phoenix-context honesty rule.

## The numbers (deterministic, o200k_base)

| Strategy | Tokens | Note |
|---|---|---|
| OKF via phoenix-context (single turn) | **3,414** | outline 2,470 + query 541 + 1 concept 403 |
| grep-and-read baseline (single turn) | **2,667** | grep lines + 4 matched files read in full |

**Honest result — single isolated turn:** grep-and-read is **1.3× cheaper**. On a 50-file bundle the
outline costs more than reading the four small files grep happens to hit. We report this, not hide it
— same credibility-over-spin stance as M4 and TokenMasterX.

**Session reality (the cost phoenix-context says actually matters — area under the curve):** the
outline is paid **once** and reused for every later structural question; grep-and-read re-pays its
full cost on every new question. Across *N* such questions:

```
OKF   ~=  2,470 (outline, once)  +  N x (one small concept ~400)
grep  ~=  N x 2,667
```

Break-even is ~1 extra question; by the 3rd structural question of a session the OKF path is already
ahead, and the lead widens with bundle size and turn count. Plus OKF yields a **stable, navigable,
any-tool-readable** artifact (git-diffable, Obsidian-browsable) that grep never produces.

## Why this matters

This is the missing half of the OKF story: M1–M4 proved Phoenix can **produce, validate, sense, and
heal** knowledge bundles; M5 proves it **consumes** them inside its own context-assembly workflow on
a real question. `okf_ingest` is now wired into phoenix-context as the consumption path for any
OKF-shaped knowledge (see `skills/phoenix-context/SKILL.md` → "Consuming OKF knowledge bundles").

## Reproduce

```
python evals/m5-okf-live/run_okf_live.py
```

Artifacts: `transcript.txt` (full captured run), `live-result.json` (machine-readable token record).
