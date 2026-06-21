"""phoenix_learn — C3: the measured-gain adoption gate for the Phoenix loop.

Ported from the live Goose continuous-learning loop (goose/tools/sia_h_run.py). A candidate
skill/prompt diff is adopted ONLY when a held-out PRIVATE split shows a real, regression-free
gain at sufficient n. The module decides eligibility; it never adopts on its own — adoption is a
human-gated step (see AGENTS.md). The decision is the honesty core; pair it with phoenix_accept
so a diff merges only behind a red->green trace.

Public surface:
  decide(...)            -> "REJECT_GAMING_DETECTED" | "EXPERIMENTAL_SMOKE_TEST"
                            | "ADOPT_ELIGIBLE" | "REJECT"
  transitions(g0, sel)   -> per-row right->right / right->wrong / wrong->right counts
  split_fixture(rows)    -> deterministic (PUBLIC, DEV, PRIVATE) ~60/20/20 by sha256(input)
  forbidden_strings(...) -> leakage-firewall set (dev/private intents, task_ids, labels, fixture)
  lint_target(target, f) -> anti-gaming lint: forbidden substrings present in a candidate
"""
from .gate import (
    ADOPT_MARGIN,
    ADOPT_MIN_N,
    ADOPT_MIN_NET,
    decide,
    transitions,
)
from .split import forbidden_strings, lint_target, split_fixture

__all__ = [
    "decide",
    "transitions",
    "split_fixture",
    "forbidden_strings",
    "lint_target",
    "ADOPT_MIN_N",
    "ADOPT_MARGIN",
    "ADOPT_MIN_NET",
]
