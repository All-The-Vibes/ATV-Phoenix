"""Prose compressor — whitespace normalisation (default) + optional ML compression.

DEFAULT PATH (use_ml=False, stdlib only, near-lossless, deterministic)
-----------------------------------------------------------------------
Applies three conservative whitespace transforms that cannot lose words:

1. Strip trailing whitespace from every line.
2. Collapse runs of 3+ consecutive blank lines down to 1.
3. Collapse internal runs of 2+ spaces into 1, EXCEPT for leading indentation
   (leading whitespace is structural in many formats and must not be touched).

None of these transforms drop words, so the round-trip word set is identical.

Large-content stashing (> 2000 chars, stash provided)
------------------------------------------------------
When the content is large enough that downstream might want aggressive trimming,
the compressor stashes the full original (ctype='prose') and appends a recovery
footer::

    --- full text: [[BR:<hash>|prose; ...; NL]] ---

This keeps the model's view compact while making the original retrievable.

OPTIONAL ML PATH (use_ml=True)
-------------------------------
Lazily imports ``llmlingua.PromptCompressor``.  If the import fails (package not
installed, CUDA unavailable, etc.) the function falls back silently to the default
path — never raises.  The recommended model is:

    microsoft/llmlingua-2-xlm-roberta-large-meetingbank

This path is OFF by default (use_ml=False) and MUST NOT be enabled in tests
because it requires downloading a large model at runtime.

DETERMINISM
-----------
The default path is byte-deterministic: same input + same opts + same stash =>
byte-identical output.  The ML path is only as deterministic as LLMLingua itself
(typically deterministic at temperature=0, but that is LLMLingua's contract, not
ours).
"""

from __future__ import annotations

import re
from typing import Optional

# Threshold above which we also stash the full original for downstream recovery.
_STASH_THRESHOLD = 2_000

# Pre-compiled patterns for the default path — compiled once at module load,
# which is cheap, and makes the per-call hot path allocation-free.
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")
# Internal multi-space: matches 2+ spaces that are NOT at the start of a line.
# The negative-lookbehind (?<!\n) and (?<!^) ensure we only touch interior runs.
# We use a non-greedy approach: match any position where the preceding char is
# not a newline (i.e. we are mid-line) and 2+ spaces follow.
_INTERIOR_MULTI_SPACE_RE = re.compile(r"(?<=\S)  +")


def _normalise_whitespace(text: str) -> str:
    """Apply near-lossless whitespace normalisation.

    1. Strip trailing whitespace per line.
    2. Collapse 3+ consecutive blank lines to a single blank line.
    3. Collapse runs of 2+ interior spaces (not leading indentation) to one space.
    """
    # Step 1: trailing whitespace
    text = _TRAILING_WS_RE.sub("", text)
    # Step 2: blank line runs (3+ newlines => 2 newlines = 1 blank line between paras)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    # Step 3: interior multi-space  (e.g. "foo  bar" -> "foo bar")
    text = _INTERIOR_MULTI_SPACE_RE.sub(" ", text)
    return text


def compress_prose(
    content: str,
    *,
    stash=None,
    rate: float = 0.5,
    use_ml: bool = False,
    **opts,
) -> str:
    """Compress prose content.

    Parameters
    ----------
    content:
        Input text (str).
    stash:
        CCR stash callable, or None.  When None the function stays lossless.
    rate:
        Target compression rate (0.0–1.0) passed to the ML path.  Ignored on
        the default path.
    use_ml:
        When True, attempt to use LLMLingua for token-level compression.
        Requires ``llmlingua`` to be installed.  Falls back to the default path
        silently on import failure.
    **opts:
        Unknown options are accepted and ignored (caller passes a shared bag).
    """
    # Guard: non-str input (e.g. None) — return empty string, never raise.
    if not isinstance(content, str):
        return ""
    # --- guard: always return str, never raise ---
    try:
        return _compress_prose_inner(content, stash=stash, rate=rate, use_ml=use_ml)
    except Exception:  # noqa: BLE001
        return content


def _compress_prose_inner(
    content: str,
    *,
    stash,
    rate: float,
    use_ml: bool,
) -> str:
    if not content:
        return content

    # ------------------------------------------------------------------
    # ML PATH (optional, lazy, falls back silently)
    # ------------------------------------------------------------------
    if use_ml:
        result = _try_ml_compress(content, stash=stash, rate=rate)
        if result is not None:
            return result
        # Fall through to default path on any ML failure.

    # ------------------------------------------------------------------
    # DEFAULT PATH — deterministic whitespace normalisation
    # ------------------------------------------------------------------
    normalised = _normalise_whitespace(content)

    # Large-content stashing: preserve the verbatim original for downstream.
    if len(content) > _STASH_THRESHOLD and stash is not None:
        placeholder = _safe_stash(content, stash=stash, ctype="prose")
        if placeholder is not None:
            normalised = normalised + f"\n\n--- full text: {placeholder} ---"

    return normalised


def _safe_stash(content: str, *, stash, ctype: str) -> Optional[str]:
    """Call stash; return None if stash returns None or raises."""
    try:
        result = stash(content, ctype=ctype)
        return result if isinstance(result, str) else None
    except Exception:  # noqa: BLE001
        return None


def _try_ml_compress(content: str, *, stash, rate: float) -> Optional[str]:
    """Attempt LLMLingua compression.  Returns None on any failure so the caller
    can fall through to the default path.

    The recommended model is microsoft/llmlingua-2-xlm-roberta-large-meetingbank.
    """
    try:
        # Lazy import — module must load even when llmlingua is absent.
        from llmlingua import PromptCompressor  # type: ignore[import]
    except ImportError:
        return None

    try:
        compressor = PromptCompressor(
            model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
            use_llmlingua2=True,
        )
        result = compressor.compress_prompt(content, rate=rate)
        compressed_text = result.get("compressed_prompt", content)
        if not isinstance(compressed_text, str) or not compressed_text:
            return None

        # If we have a stash, preserve the original so it's recoverable.
        if stash is not None:
            placeholder = _safe_stash(content, stash=stash, ctype="prose")
            if placeholder is not None:
                compressed_text = compressed_text + f"\n\n--- full text: {placeholder} ---"

        return compressed_text
    except Exception:  # noqa: BLE001
        return None
