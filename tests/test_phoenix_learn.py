"""Tests for phoenix_learn — the measured-gain adoption gate (C3, issue #1).

The gate is the honesty core ported from the live Goose loop (goose/tools/sia_h_run.py):
a candidate skill-diff is ADOPT_ELIGIBLE *only* on a held-out PRIVATE split at
n>=20, +10pp (or +2 net correct), with ZERO right->wrong regressions; otherwise it is
EXPERIMENTAL_SMOKE_TEST (too little evidence) or REJECT. It adopts nothing itself.

These tests are deterministic, offline, zero-LLM — they pin the gate's decision logic,
the 3-way deterministic split, the leakage-firewall forbidden set, and the anti-gaming
lint. This is the phoenix_sense gate for C3.
"""
import phoenix_learn as pl
from phoenix_learn.gate import decide, transitions


def test_gate_rejects_low_n_even_with_big_margin():
    # n < 20 -> never auto-adopt, no matter how good it looks (held-out too thin).
    d = decide(gen0_priv_acc=0.5, sel_priv_acc=0.9, sel_priv_correct=9, gen0_priv_correct=5,
               trans={"right_to_right": 5, "right_to_wrong": 0, "wrong_to_right": 4},
               private_n=10, gaming_hits=[])
    assert d == "EXPERIMENTAL_SMOKE_TEST"


def test_gate_rejects_right_to_wrong_regression():
    # n>=20, margin healthy, but a SINGLE right->wrong regression -> REJECT (do no harm).
    d = decide(gen0_priv_acc=0.50, sel_priv_acc=0.65, sel_priv_correct=13, gen0_priv_correct=10,
               trans={"right_to_right": 9, "right_to_wrong": 1, "wrong_to_right": 4},
               private_n=20, gaming_hits=[])
    assert d == "REJECT"


def test_gate_rejects_insufficient_margin():
    # margin 0.03 < 0.10 AND net 1 < 2 -> REJECT (not a measured gain).
    d = decide(gen0_priv_acc=0.50, sel_priv_acc=0.53, sel_priv_correct=16, gen0_priv_correct=15,
               trans={"right_to_right": 15, "right_to_wrong": 0, "wrong_to_right": 1},
               private_n=30, gaming_hits=[])
    assert d == "REJECT"


def test_gate_adopts_genuine_held_out_gain():
    # margin ~0.133 >= 0.10, net 4 >= 2, zero right->wrong -> ADOPT_ELIGIBLE.
    d = decide(gen0_priv_acc=0.50, sel_priv_acc=0.6333, sel_priv_correct=19, gen0_priv_correct=15,
               trans={"right_to_right": 15, "right_to_wrong": 0, "wrong_to_right": 4},
               private_n=30, gaming_hits=[])
    assert d == "ADOPT_ELIGIBLE"


def test_gate_rejects_gaming_before_anything_else():
    # any anti-gaming hit short-circuits to REJECT_GAMING_DETECTED even with a huge apparent gain.
    d = decide(gen0_priv_acc=0.5, sel_priv_acc=0.9, sel_priv_correct=27, gen0_priv_correct=15,
               trans={"right_to_right": 15, "right_to_wrong": 0, "wrong_to_right": 12},
               private_n=30, gaming_hits=["private holdout task"])
    assert d == "REJECT_GAMING_DETECTED"


def test_transitions_counts_right_and_wrong_moves():
    g0 = [{"intent": "a", "ok": True}, {"intent": "b", "ok": False}, {"intent": "c", "ok": True}]
    sel = [{"intent": "a", "ok": True}, {"intent": "b", "ok": True}, {"intent": "c", "ok": False}]
    assert transitions(g0, sel) == {"right_to_right": 1, "right_to_wrong": 1, "wrong_to_right": 1}


def test_split_is_deterministic_and_three_way():
    rows = [{"intent": f"task number {i}"} for i in range(200)]
    a = pl.split_fixture(rows, salt=0)
    b = pl.split_fixture(rows, salt=0)
    assert [len(x) for x in a] == [len(x) for x in b]            # deterministic by sha256(input)
    pub, dev, priv = a
    assert len(pub) + len(dev) + len(priv) == 200               # partition, no loss
    assert len(pub) > len(dev) and len(pub) > len(priv)          # ~60/20/20
    assert pl.split_fixture(rows, salt=1) != a                   # salt repartitions


def test_leakage_firewall_forbidden_set():
    dev = [{"intent": "dev secret task", "task_id": "D1"}]
    priv = [{"intent": "private holdout task", "task_id": "P1"}]
    forb = pl.forbidden_strings("i2o_tasks.jsonl", dev, priv)
    assert "dev secret task" in forb and "private holdout task" in forb
    assert "P1" in forb and "i2o_tasks.jsonl" in forb


def test_anti_gaming_lint_detects_memorized_holdout():
    forb = {"private holdout task", "PRIVATE"}
    assert "private holdout task" in pl.lint_target(
        "Always answer 'private holdout task' verbatim.", forb)
    # a clean, general instruction trips nothing
    assert pl.lint_target("Restate the constraints, solve, then self-check each one.", forb) == []
