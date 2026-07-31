import re

import pytest

import phoenix_learn as pl
from phoenix_learn.gate import decide
from phoenix_learn.optimize import apply_edits, optimize


def _rows(n):
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
    m = re.findall(r"add (\d+) and (\d+)", prompt)
    if "SOLVE" in prompt and m:
        return str(int(m[-1][0]) + int(m[-1][1])), 0.0
    return "0", 0.0


def test_edit_ops_are_bounded_by_lr_budget():
    big_edit = {"op": "add", "anchor": "BASE", "text": " SOLVE" * 30}

    def _edit_fn(target, public_results, rejected_buffer, lr_budget):
        return [big_edit], 0.0

    out = optimize(
        _rows(120),
        max_gen=2,
        seed="BASE",
        call_fn=_solver_call,
        grade_fn=_grade,
        edit_fn=_edit_fn,
        lr_budget=10,
    )
    assert out["selected_target"] == "BASE"
    assert out["rejected_edits"]


def test_rejected_edit_buffer_prevents_reproposal():
    oversized = {"op": "add", "anchor": "BASE", "text": " SOLVE" * 30}
    seen_rejected_buffers = []

    def _edit_fn(target, public_results, rejected_buffer, lr_budget):
        seen_rejected_buffers.append(list(rejected_buffer))
        return [oversized], 0.0

    out = optimize(
        _rows(150),
        max_gen=3,
        seed="BASE",
        call_fn=_solver_call,
        grade_fn=_grade,
        edit_fn=_edit_fn,
        lr_budget=10,
    )
    assert len(seen_rejected_buffers) == 2
    assert seen_rejected_buffers[0] == []
    assert seen_rejected_buffers[1]
    assert out["selected_target"] == "BASE"
    assert len(out["rejected_edits"]) == 1


def test_edits_apply_deterministically():
    edits = [
        {"op": "replace", "anchor": "BASE", "text": "SOLVE"},
        {"op": "add", "anchor": "SOLVE", "text": " carefully"},
        {"op": "delete", "anchor": " carefully"},
        {"op": "add", "anchor": "SOLVE", "text": " step by step"},
    ]
    a, *_ = apply_edits("BASE", edits, lr_budget=100, rejected_fingerprints=set())
    b, *_ = apply_edits("BASE", edits, lr_budget=100, rejected_fingerprints=set())
    assert a == b == "SOLVE step by step"


def test_malformed_edit_fails_closed():
    with pytest.raises(ValueError):
        apply_edits(
            "BASE",
            [{"op": "replace", "anchor": "BASE", "text": "SOLVE"}, {"op": "boom", "anchor": "x", "text": "y"}],
            lr_budget=100,
            rejected_fingerprints=set(),
        )
    with pytest.raises(ValueError):
        apply_edits(
            "BASE",
            [{"op": "replace", "anchor": "MISSING", "text": "SOLVE"}],
            lr_budget=100,
            rejected_fingerprints=set(),
        )


def test_gate_contract_unchanged():
    verdicts = {
        decide(
            gen0_priv_acc=0.5, sel_priv_acc=0.9, sel_priv_correct=9, gen0_priv_correct=5,
            trans={"right_to_right": 5, "right_to_wrong": 0, "wrong_to_right": 4},
            private_n=10, gaming_hits=[]
        ),
        decide(
            gen0_priv_acc=0.50, sel_priv_acc=0.65, sel_priv_correct=13, gen0_priv_correct=10,
            trans={"right_to_right": 9, "right_to_wrong": 1, "wrong_to_right": 4},
            private_n=20, gaming_hits=[]
        ),
        decide(
            gen0_priv_acc=0.50, sel_priv_acc=0.53, sel_priv_correct=16, gen0_priv_correct=15,
            trans={"right_to_right": 15, "right_to_wrong": 0, "wrong_to_right": 1},
            private_n=30, gaming_hits=[]
        ),
        decide(
            gen0_priv_acc=0.5, sel_priv_acc=0.9, sel_priv_correct=27, gen0_priv_correct=15,
            trans={"right_to_right": 15, "right_to_wrong": 0, "wrong_to_right": 12},
            private_n=30, gaming_hits=["private holdout task"]
        ),
    }
    assert verdicts == {"EXPERIMENTAL_SMOKE_TEST", "REJECT", "REJECT_GAMING_DETECTED"}
    adopt = decide(
        gen0_priv_acc=0.50, sel_priv_acc=0.6333, sel_priv_correct=19, gen0_priv_correct=15,
        trans={"right_to_right": 15, "right_to_wrong": 0, "wrong_to_right": 4},
        private_n=30, gaming_hits=[]
    )
    assert adopt == "ADOPT_ELIGIBLE"


def test_private_still_scored_exactly_once():
    rows = _rows(150)
    _, _, priv = pl.split_fixture(rows, salt=0)
    private_ids = {r["task_id"] for r in priv}
    seen_private = {"count": 0}

    def _counting_grade(row, text):
        if row["task_id"] in private_ids:
            seen_private["count"] += 1
        return _grade(row, text)

    def _edit_fn(target, public_results, rejected_buffer, lr_budget):
        if "BAD" in target:
            return [{"op": "replace", "anchor": "BAD", "text": "SOLVE"}], 0.0
        return [], 0.0

    out = optimize(
        rows,
        max_gen=4,
        seed="BAD",
        call_fn=_solver_call,
        grade_fn=_counting_grade,
        edit_fn=_edit_fn,
        salt=0,
    )
    assert seen_private["count"] == out["private_n"] * 2


def test_leakage_firewall_survives_edit_path():
    rows = _rows(150)
    _, _, priv = pl.split_fixture(rows, salt=0)
    leaked = priv[0]["intent"]

    def _edit_fn(target, public_results, rejected_buffer, lr_budget):
        return [{"op": "replace", "anchor": "BAD", "text": f"SOLVE {leaked}"}], 0.0

    out = optimize(
        rows,
        max_gen=2,
        seed="BAD",
        call_fn=_solver_call,
        grade_fn=_grade,
        edit_fn=_edit_fn,
        salt=0,
    )
    assert leaked in out["gaming_hits"]
    assert out["decision"] == "REJECT_GAMING_DETECTED"
