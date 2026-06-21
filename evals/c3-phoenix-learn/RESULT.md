# C3 — `phoenix-learn`: measured-gain adoption gate (RESULT)

**Date:** 2026-06-20 · **Release:** 0.4.0 · **PR:** #7 (`feat/c3-phoenix-learn`, human-gated)

## What this demonstrates

The first Phoenix *connector* built **by** Phoenix: the measured-gain adoption gate ported from the live
continuous-learning loop. A candidate skill/prompt diff is `ADOPT_ELIGIBLE` **only** on a held-out PRIVATE
split that proves a real, regression-free gain — never on a self-graded hunch. It was built **failure-first
through the shipped `phoenix-mcp` binary**, so completion is *demonstrated* from a tamper-evident
red → green trace, not asserted.

This is the **first slice** — the deterministic gate core (decision + split + firewall + lint). The
optimizer that *proposes* candidates (a GEPA-style reflect/mutate loop over a real held-out fixture, under
this same gate) is the next slice.

## Gate semantics (`phoenix_learn/gate.py`)

| Verdict | Condition (measured on the held-out PRIVATE split) |
| --- | --- |
| `REJECT_GAMING_DETECTED` | any anti-gaming lint hit (short-circuits everything) |
| `EXPERIMENTAL_SMOKE_TEST` | `private_n < 20` — too little held-out evidence to trust |
| `ADOPT_ELIGIBLE` | `n ≥ 20` **and** `+10pp` (or `+2` net correct) **and** zero `right→wrong` **and** strictly better than baseline |
| `REJECT` | everything else |

The gate **decides eligibility; it never adopts** — adoption is a human-gated step (see `AGENTS.md`).
Supporting pieces (`phoenix_learn/split.py`): a deterministic sha256 3-way split (~60/20/20, PRIVATE
scored once), a leakage firewall (`forbidden_strings`), and an anti-gaming lint (`lint_target`).

## Built failure-first under the Phoenix loop

Driven through the real `phoenix-mcp` stdio binary (not a hand-built trace):

1. Wrote `tests/test_phoenix_learn.py` — 9 deterministic, offline, zero-LLM cases.
2. `phoenix_sense` → **RED** (`ok:false`, `ModuleNotFoundError: No module named 'phoenix_learn'`, exit 2).
3. Implemented `phoenix_learn/` (gate + split).
4. `phoenix_sense` → **GREEN** (`ok:true`, `9 passed`).
5. `phoenix_accept` → **PROOF**:

```json
{"ok":true,
 "check_digest":"441a68e481603e71d182b9881171c3127db4b9143f731efc5e6c64b3ca19c140",
 "trace_intact":true,"saw_red":true,"green_after_red":true,"currently_green":true,
 "reason":"failure-first satisfied: red->green in an intact trace, currently green"}
```

`phoenix_verify_trace` → `{"ok":true,"rows":9,"head_hash":"98a229f3…","broken_at":null}`.

## The 9 gate tests (what each pins)

| Test | Pins |
| --- | --- |
| `test_gate_rejects_low_n_even_with_big_margin` | `n<20` → `EXPERIMENTAL_SMOKE_TEST` regardless of apparent gain |
| `test_gate_rejects_right_to_wrong_regression` | a single `right→wrong` at healthy margin → `REJECT` (do no harm) |
| `test_gate_rejects_insufficient_margin` | margin `<10pp` and net `<2` → `REJECT` |
| `test_gate_adopts_genuine_held_out_gain` | `+13pp`, net `+4`, zero regression, `n=30` → `ADOPT_ELIGIBLE` |
| `test_gate_rejects_gaming_before_anything_else` | any gaming hit short-circuits → `REJECT_GAMING_DETECTED` |
| `test_transitions_counts_right_and_wrong_moves` | per-row right→right / right→wrong / wrong→right counting |
| `test_split_is_deterministic_and_three_way` | same input → same split; ~60/20/20; salt repartitions |
| `test_leakage_firewall_forbidden_set` | dev/private intents + task_ids + fixture name enter the firewall |
| `test_anti_gaming_lint_detects_memorized_holdout` | a memorized held-out string is flagged; a clean instruction is not |

## Enforcement

The test is wired into the local gate (`scripts/ci-local.{sh,ps1}`); the **pre-push hook ran the full gate
green and gated the push** (cargo test `--locked` + OKF pytest + `phoenix-learn` + both OKF bundles). Zero
GitHub Action credits spent.

## Reproduce

```powershell
cd ATV-Phoenix
python -m pytest tests/test_phoenix_learn.py -q   # 9 passed, offline, zero-LLM
pwsh -NoProfile -File scripts/ci-local.ps1        # full local gate
```
