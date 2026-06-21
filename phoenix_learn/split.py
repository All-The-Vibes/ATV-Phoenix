"""Deterministic fixture split + leakage firewall (ported from goose/tools/sia_h_run.py).

split_fixture hashes each row's intent (with an optional salt) into a stable bucket so the
PUBLIC/DEV/PRIVATE partition is reproducible across runs and machines — the PRIVATE split is
scored exactly once, never used for selection. forbidden_strings + lint_target form the
anti-gaming firewall: a candidate that embeds a held-out task, a split label, or the fixture
name verbatim is memorizing the test rather than generalizing, and is rejected.
"""
from __future__ import annotations

import hashlib
import os

# Bucket boundaries: [0,60) PUBLIC, [60,80) DEV, [80,100) PRIVATE  -> ~60/20/20.
_PUBLIC_MAX = 60
_DEV_MAX = 80

# Split labels must never appear verbatim in a candidate (would signal split-targeting).
_SPLIT_LABELS = ("PUBLIC", "DEV", "PRIVATE", "private split", "held-out", "holdout")


def split_fixture(rows, salt=0):
    """Partition rows into (public, dev, private) deterministically by sha256(salt|intent)."""
    public, dev, private = [], [], []
    for row in rows:
        key = f"{salt}|{row['intent']}".encode("utf-8")
        bucket = int(hashlib.sha256(key).hexdigest(), 16) % 100
        if bucket < _PUBLIC_MAX:
            public.append(row)
        elif bucket < _DEV_MAX:
            dev.append(row)
        else:
            private.append(row)
    return public, dev, private


def forbidden_strings(fixture_name, dev_rows, priv_rows):
    """Build the leakage-firewall set: anything a clean candidate must not quote verbatim."""
    bad = set(_SPLIT_LABELS)
    if fixture_name:
        bad.add(os.path.basename(fixture_name))
    for row in list(dev_rows) + list(priv_rows):
        intent = row.get("intent")
        if intent:
            bad.add(intent)
        task_id = row.get("task_id")
        if task_id:
            bad.add(task_id)
    return {s for s in bad if s}


def lint_target(target, forbidden):
    """Return the sorted forbidden substrings present in `target` (case-insensitive). Empty == clean."""
    text = (target or "").casefold()
    return sorted({s for s in forbidden if s and s.casefold() in text})
