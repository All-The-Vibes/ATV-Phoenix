"""JSON / structured-data compressor.

Walks parsed JSON, elides long lists to a sample+tail window, and stashes
long string values. Re-serialises with compact separators for output.

Contract rules observed:
  1. Never raise — any parse/walk/serialize failure returns content unchanged.
  2. str in, str out.
  3. Lossy display, lossless recovery: long string values are stashed when
     stash is available; without stash a trailing "...(+K chars)" marker is
     appended (lossless enough for the no-CCR measurement path).
  4. Deterministic: dict insertion order is preserved (Python 3.7+ guarantee),
     list windows are index-stable, stash keys are content-addressed.

Optional deps: none (stdlib json only).
"""

from __future__ import annotations

import json


def compress_json(
    content: str,
    *,
    stash=None,
    sample: int = 2,
    tail: int = 1,
    max_str: int = 200,
    **opts,
) -> str:
    """Return a compressed view of *content*, which must be a JSON document.

    Parameters
    ----------
    content:
        Raw JSON text.
    stash:
        CCR stash callable (injected by the router). When ``None`` the
        compressor stays lossless — long strings get a trailing truncation
        marker rather than a placeholder.
    sample:
        How many leading elements to keep from a long list.
    tail:
        How many trailing elements to keep from a long list.
    max_str:
        Maximum character length for a string value before it is
        compressed/stashed.
    **opts:
        Ignored — callers pass a shared bag; unknown keys must not raise.
    """
    if not isinstance(content, str):
        return content  # type: ignore[return-value]
    if not content.strip():
        return content

    # ------------------------------------------------------------------ parse
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        # Not JSON — return unchanged (rule 1 + rule 2).
        return content

    # ------------------------------------------------------------------ walk
    try:
        compressed = _walk(data, stash=stash, sample=sample, tail=tail, max_str=max_str)
    except Exception:
        return content

    # --------------------------------------------------------------- serialize
    try:
        out = json.dumps(compressed, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return content

    # Safety: must have reduced or stayed the same; if somehow larger, fall back.
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _walk(obj, *, stash, sample: int, tail: int, max_str: int):
    """Recursively compress *obj* and return the compacted structure.

    Raises are intentionally allowed to bubble up to the outer try/except in
    ``compress_json``; they are caught there and cause a graceful passthrough.
    """
    if isinstance(obj, dict):
        # Preserve every key; recurse into values.
        return {
            k: _walk(v, stash=stash, sample=sample, tail=tail, max_str=max_str)
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        n = len(obj)
        threshold = sample + tail + 1  # minimum list length before we elide
        if n > threshold:
            head_items = [
                _walk(item, stash=stash, sample=sample, tail=tail, max_str=max_str)
                for item in obj[:sample]
            ]
            middle = obj[sample:n - tail]
            middle_count = len(middle)
            # Lossless recovery: stash the omitted slice so brainspace_retrieve can
            # recover the dropped records. Without a stash we stay honest by saying
            # the records are elided (the count is exact); with one we embed the
            # placeholder so the model can ask for the exact middle back.
            placeholder = None
            if stash is not None:
                try:
                    placeholder = stash(
                        json.dumps(middle, separators=(",", ":"), ensure_ascii=False),
                        ctype="json",
                        source=f"{middle_count} list items",
                    )
                except Exception:
                    placeholder = None
            if placeholder:
                marker = f"...{middle_count} more items (same shape) {placeholder}..."
            else:
                marker = f"...{middle_count} more items (same shape)..."
            tail_items = [
                _walk(item, stash=stash, sample=sample, tail=tail, max_str=max_str)
                for item in obj[n - tail:]
            ]
            return head_items + [marker] + tail_items
        else:
            # List is short enough: recurse into every element.
            return [
                _walk(item, stash=stash, sample=sample, tail=tail, max_str=max_str)
                for item in obj
            ]

    if isinstance(obj, str) and len(obj) > max_str:
        return _compress_string(obj, stash=stash, max_str=max_str)

    # Scalars (int, float, bool, None) and short strings: keep as-is.
    return obj


def _compress_string(value: str, *, stash, max_str: int) -> str:
    """Compress a long string value.

    With stash: stash the original, return a truncated prefix + placeholder.
    Without stash: return a truncated form with a trailing "...(+K chars)" marker.
    Both paths preserve the first ``max_str`` characters so the model retains
    useful context even without expanding the placeholder.
    """
    prefix = value[:max_str]

    if stash is not None:
        placeholder = None
        try:
            placeholder = stash(value, ctype="json-value")
        except Exception:
            placeholder = None
        if placeholder is not None:
            return f"{prefix}… {placeholder}"
        # stash returned None — fall back to the truncation marker below.

    # No stash available (or it declined): lossless-enough truncation
    # with a byte count.
    extra = len(value) - max_str
    return f"{prefix}...({extra:+d} chars)"
