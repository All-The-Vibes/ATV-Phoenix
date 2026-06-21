"""Tests for phoenix_learn.optimize — the candidate-proposing optimizer (C3, issue #1).

The gate (issue #7) decides eligibility; this slice is the *proposer* that feeds it: a GEPA-style
generational loop ported from the live Goose loop (goose/tools/sia_h_run.py:run). It synthesizes a
gen_0 instruction from PUBLIC prompts only, reflect/mutates against PUBLIC failures, SELECTS the best
generation on DEV, scores the held-out PRIVATE split EXACTLY ONCE, runs the leakage firewall +
anti-gaming lint, and routes the result through phoenix_learn.gate.decide. It PROPOSES; it never
adopts (adoption stays human-gated behind a phoenix_accept red->green trace, per AGENTS.md).

These tests are deterministic, offline, zero-LLM: every model touch point is an injected callable.
This is the phoenix_sense gate for the optimizer slice of C3.
"""
import re

import phoenix_learn as pl
from phoenix_learn.optimize import (
    build_feedback_prompt,
    build_meta_prompt,
    optimize,
    score,
)


# --- offline fixtures + injected stubs (zero LLM) ---------------------------------------------
def _rows(n):
    # "add i and i" -> 2*i ; deterministic, well-distributed, audited-style grader shape.
    return [{"task_id": f"t{i}", "intent": f"add {i} and {i}",
             "grader": {"match": "numeric", "answer_format": "<number>", "expected": 2 * i}}
            for i in range(1, n + 1)]


def _grade(row, text):
    try:
        got = str(int(float(text)))
    except Exception:
        got = ""
    return got == str(row["grader"]["expected"]), got


def _solver_call(prompt):
    # solves "add A and B" only when the prepended target carries the 'SOLVE' token.
    m = re.findall(r"add (\d+) and (\d+)", prompt)
    if "SOLVE" in prompt and m:
        return str(int(m[-1][0]) + int(m[-1][1])), 0.0
    return "0", 0.0


_BAD_META = lambda pub: ("BAD", 0.0)              # gen_0 carries no SOLVE token -> all wrong
_GOOD_FB = lambda target, pubres: ("SOLVE step by step", 0.0)   # adds the token -> all right


# --- the optimizer routes a genuine held-out gain through the real gate -----------------------
def test_optimizer_reaches_adopt_eligible_on_genuine_gain():
    out = optimize(_rows(150), max_gen=2, salt=0, call_fn=_solver_call,
                   meta_fn=_BAD_META, feedback_fn=_GOOD_FB, grade_fn=_grade)
    assert out["private_n"] >= 20                                   # enough held-out evidence
    assert out["gen0_private_acc"] <= 0.1                           # baseline fails
    assert out["selected_private_acc"] >= 0.9                       # improved candidate solves
    assert out["private_transitions"]["right_to_wrong"] == 0        # does no harm
    assert out["decision"] == "ADOPT_ELIGIBLE"                      # ...so the gate clears it


# --- small held-out n is never adopt-eligible, however good it looks --------------------------
def test_optimizer_smoke_tests_when_private_too_thin():
    out = optimize(_rows(24), max_gen=2, salt=0, call_fn=_solver_call,
                   meta_fn=_BAD_META, feedback_fn=_GOOD_FB, grade_fn=_grade)
    assert out["private_n"] < 20
    assert out["decision"] == "EXPERIMENTAL_SMOKE_TEST"


# --- a selected candidate that memorizes a split label is rejected as gaming ------------------
def test_optimizer_rejects_gaming_candidate():
    gamed_fb = lambda target, pubres: ("SOLVE using the PRIVATE split", 0.0)   # high acc + leak
    out = optimize(_rows(150), max_gen=2, salt=0, call_fn=_solver_call,
                   meta_fn=_BAD_META, feedback_fn=gamed_fb, grade_fn=_grade)
    assert out["gaming_hits"]                                       # firewall tripped
    assert out["decision"] == "REJECT_GAMING_DETECTED"


# --- a worse candidate keeps the baseline; verdict is REJECT, never silent adoption -----------
def test_optimizer_rejects_when_no_measured_gain():
    flat = lambda prompt: ("0", 0.0)                               # nothing ever solves
    out = optimize(_rows(150), max_gen=2, salt=0, call_fn=flat,
                   meta_fn=_BAD_META, feedback_fn=_GOOD_FB, grade_fn=_grade)
    assert out["selected_private_acc"] <= 0.1
    assert out["decision"] == "REJECT"


# --- PRIVATE is scored once: it must never appear in the public/dev selection curve -----------
def test_private_split_never_leaks_into_selection_curve():
    out = optimize(_rows(150), max_gen=3, salt=0, call_fn=_solver_call,
                   meta_fn=_BAD_META, feedback_fn=_GOOD_FB, grade_fn=_grade)
    assert out["curve"], "expected per-generation selection metadata"
    assert all("private" not in key for gen in out["curve"] for key in gen)


# --- a hand seed is used verbatim for gen_0; the meta synthesizer must not run -----------------
def test_seed_target_skips_meta_synthesis():
    def _boom(pub):
        raise AssertionError("meta_fn must not run when a seed is supplied")
    out = optimize(_rows(150), max_gen=1, salt=0, seed="SOLVE", call_fn=_solver_call,
                   meta_fn=_boom, feedback_fn=_GOOD_FB, grade_fn=_grade)
    assert out["selected_private_acc"] >= 0.9


# --- the meta + feedback prompts must never quote a dev/private input (leakage firewall) -------
def test_prompts_do_not_leak_held_out_inputs():
    rows = _rows(150)
    pub, dev, priv = pl.split_fixture(rows, salt=0)
    leak_terms = [r["intent"] for r in dev + priv]
    meta_p = build_meta_prompt(pub)
    fb_p = build_feedback_prompt("CUR", [{"intent": pub[0]["intent"], "got": "x", "ok": False}])
    assert not any(t in meta_p for t in leak_terms)
    assert not any(t in fb_p for t in leak_terms)


# --- score() prepends the target and grades with the audited grader ---------------------------
def test_score_uses_target_and_audited_grader():
    rows = _rows(6)
    hit = score("SOLVE", rows, _solver_call, _grade)
    miss = score("nope", rows, _solver_call, _grade)
    assert hit["acc"] == 1.0 and hit["correct"] == 6 and hit["n"] == 6
    assert miss["correct"] == 0


# --- the optimizer proposes a verdict but adopts nothing (no input mutation, pure return) ------
def test_optimizer_proposes_but_does_not_adopt():
    rows = _rows(150)
    before = [dict(r) for r in rows]
    out = optimize(rows, max_gen=2, salt=0, call_fn=_solver_call,
                   meta_fn=_BAD_META, feedback_fn=_GOOD_FB, grade_fn=_grade)
    assert out["decision"] in {
        "ADOPT_ELIGIBLE", "EXPERIMENTAL_SMOKE_TEST", "REJECT", "REJECT_GAMING_DETECTED"}
    assert rows == before                                          # inputs untouched
