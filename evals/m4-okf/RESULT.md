# Milestone M4 — OKF is self-sensing AND measured

**Date:** 2026-06-17
**Goal:** (1) Wire OKF conformance + freshness into the Phoenix spine as objective `phoenix_sense`
checks so a derived bundle can't silently rot, and (2) measure — with real token counts — whether
index-first OKF consumption actually beats the alternatives.
**Verdict:** ✅ PASS — the real `phoenix-mcp` binary SENSED an OKF conformance fault and proved a
red→green heal in a tamper-evident trace; index-first consumption is **31x** cheaper than the
opaque `graph.json` and wins the session view against every alternative (honest grep nuance below).

---

## Part 1 — Sense + freshness (wired into the spine)

No Rust change was needed: the spine's existing `command_exit` sense kind runs the Python gates,
keeping the spine minimal (OKF domain logic stays in portable skill scripts).

**New capability:** `skills/phoenix-okf/scripts/okf_freshness.py` — compares the `built_at_commit`
anchored in the bundle's root `index.md` against the current `graph.json`. `exit 0 = FRESH`,
`exit 1 = STALE`. Proven both directions (FRESH on the live graph; STALE against a fabricated
commit).

**Committed sense recipes** (`skills/phoenix-okf/checks/`): `okf-conformant.json`, `okf-fresh.json`
— ready-to-run `command_exit` checks Copilot/Scout can pass straight to `phoenix_sense`.

**Full red→green chain through the real `target/release/phoenix-mcp.exe`:**
```
1. sense  okf-conformant   -> ok=true   GREEN  (50 concepts, CONFORMANT)
2. sense  okf-fresh        -> ok=true   GREEN  (bundle & graph at d08041dc7fbd)
   << inject fault: strip `type:` from concepts/src/heal.rs.md >>
4. sense  okf-conformant   -> ok=false  RED    (ERROR concepts/src/heal.rs.md: missing `type` S9.2)
5. heal   re-export bundle from graph.json
6. sense  okf-conformant   -> ok=true   GREEN
7. accept okf-conformant   -> ok=true   {saw_red:true, green_after_red:true, currently_green:true,
                                          trace_intact:true} "failure-first satisfied: red→green"
8. verify-trace            -> ok=true   rows=4, chain intact
```
This is the M1/M2 self-heal pattern applied to knowledge artifacts: a bundle that drifts or is
corrupted produces an objective RED a run can heal (re-export), proven from the hash-chained trace
— not asserted.

## Part 2 — Measure it (tiktoken `o200k_base`, deterministic, no model called)

`evals/m4-okf/run_okf_eval.py` answers four representative knowledge questions on the committed
`examples/okf-code-graph/` bundle (50 concepts) four ways. Tokens = context that must be loaded to
answer.

**Per-question (single-shot), tokens:**

| Question | raw graph.json | whole bundle | grep+read | OKF index-first |
|---|--:|--:|--:|--:|
| cross-file calls of `main()` | 90,067 | 17,911 | 483 | 2,822 |
| blast radius of `phoenix_mcp.rs` | 90,067 | 17,911 | 1,034 | 3,358 |
| frontmatter of `heal.rs` | 90,067 | 17,911 | 2,667 | 2,873 |
| list all Rust Source concepts | 90,067 | 17,911 | 4,594 | 2,470 |

**Session view (4 questions; reusable context loaded once, grep re-paid per question):**

| Strategy | tokens | vs index-first |
|---|--:|--:|
| raw `graph.json` | 90,067 | 21.9x |
| whole bundle dump | 17,911 | 4.4x |
| grep + read | 8,778 | 2.1x |
| **OKF index-first** | **4,113** | **1.0x** |

**Headlines:**
- **31.3x** fewer tokens than loading the opaque `graph.json` (the status-quo artifact), single-shot.
- **4.4x** fewer than dumping the whole bundle "for context."
- **2.1x** fewer than grep-the-bundle across the session.

**Honest negative (reported, per Phoenix ethos):** on this *small* 50-file bundle, *single-shot*
grep is actually competitive — even marginally cheaper on the whole-session sum (8,778 vs 11,523)
when the 2,470-token outline is re-charged to every question. The index-first advantage over grep
comes from (a) amortizing the outline once per session, (b) larger bundles where grep's hit-set and
re-reads explode, and (c) multi-turn area-under-curve, where grep re-reads compound and the outline
does not. Against the opaque graph and the whole-bundle dump, index-first wins decisively in every
framing — and uniquely yields a stable, navigable, any-tool-readable artifact grep never produces.

## Reproduce
```
python skills/phoenix-okf/scripts/okf_freshness.py examples/okf-code-graph
target/release/phoenix-mcp.exe sense  @skills/phoenix-okf/checks/okf-conformant.json
target/release/phoenix-mcp.exe accept @skills/phoenix-okf/checks/okf-conformant.json
python evals/m4-okf/run_okf_eval.py
```

## Files
- `skills/phoenix-okf/scripts/okf_freshness.py` — staleness sense.
- `skills/phoenix-okf/checks/{okf-conformant,okf-fresh}.json` — sense recipes.
- `evals/m4-okf/run_okf_eval.py`, `results.jsonl` — the token measurement.
