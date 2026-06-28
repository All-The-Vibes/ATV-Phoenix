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
  optimize(rows, ...)    -> generational propose->select->measure loop; advisory gate verdict
  build_meta_prompt/build_feedback_prompt/score -> the PUBLIC-only proposer primitives
"""
from .gate import (
    ADOPT_MARGIN,
    ADOPT_MIN_N,
    ADOPT_MIN_NET,
    decide,
    transitions,
)
from .optimize import (
    build_feedback_prompt,
    build_meta_prompt,
    optimize,
    score,
)
from .split import forbidden_strings, lint_target, split_fixture
from .graded import (
    ACCEPT,
    REJECT,
    REVIEW,
    grade,
    is_accept,
    summary,
)

__all__ = [
    "decide",
    "transitions",
    "split_fixture",
    "forbidden_strings",
    "lint_target",
    "optimize",
    "build_meta_prompt",
    "build_feedback_prompt",
    "score",
    "ADOPT_MIN_N",
    "ADOPT_MARGIN",
    "ADOPT_MIN_NET",
    "grade",
    "is_accept",
    "summary",
    "ACCEPT",
    "REVIEW",
    "REJECT",
]
