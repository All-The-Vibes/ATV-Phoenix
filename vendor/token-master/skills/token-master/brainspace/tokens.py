"""Token-count proxy for measuring compression reduction.

We do not have the host model's exact tokenizer, and we must not require a heavy
dependency just to report a savings number. So ``estimate`` prefers ``tiktoken``
(the closest widely-available BPE proxy) when it is importable, and otherwise
falls back to a character-based heuristic.

The fallback uses ~4 characters/token, the long-standing rule of thumb for
English+code mixed text. It is only a proxy: reduction *ratios* are stable across
both backends even when absolute counts differ, and ratios are what we report.
"""

from __future__ import annotations

_ENCODER = None
_TRIED = False


def _encoder():
    """Lazy-load a tiktoken encoder once; cache the failure too so we don't retry."""
    global _ENCODER, _TRIED
    if _TRIED:
        return _ENCODER
    _TRIED = True
    try:
        import tiktoken  # optional dependency

        # cl100k_base is a reasonable cross-model BPE proxy and ships with tiktoken.
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:  # ImportError, network fetch failure, etc. — degrade quietly
        _ENCODER = None
    return _ENCODER


def estimate(text: str) -> int:
    """Estimate the token count of ``text``.

    Uses tiktoken when available, else a 4-chars/token heuristic. Always returns a
    non-negative int and never raises.
    """
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # Heuristic fallback: ceil(len / 4).
    return (len(text) + 3) // 4


def reduction(before: str, after: str) -> dict:
    """Return a small report dict comparing two strings by estimated tokens."""
    b = estimate(before)
    a = estimate(after)
    saved = b - a
    pct = (saved / b * 100.0) if b else 0.0
    ratio = (b / a) if a else float("inf")
    return {
        "tokens_before": b,
        "tokens_after": a,
        "tokens_saved": saved,
        "pct_reduction": round(pct, 1),
        "ratio": round(ratio, 2) if a else None,
        "backend": "tiktoken" if _encoder() is not None else "heuristic",
    }
