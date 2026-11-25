"""Log / build-output compressor.

Collapses runs of repeated identical lines and severity-aware elision:
  * Repeated identical lines -> ``line (xN)``
  * Lines matching ERROR|FATAL|CRITICAL|WARN|Exception|Traceback are kept
    verbatim, along with ``context`` lines before and after each.
  * Long runs of unimportant lines (INFO/DEBUG/blank/etc.) are replaced with
    a single ``... {K} lines elided ...`` marker.
  * When a stash is provided the FULL original is stashed (ctype='log') and a
    final ``full log: <placeholder>`` line is appended so the model can ask
    for everything back.  When stash is None the elision markers remain
    (still honest: counts are exact, so recovery is conceptually possible
    from the original).

Contract rules observed:
  1. Never raise -- any failure returns content unchanged.
  2. str in, str out.
  3. Lossy display, lossless recovery via stash.
  4. Deterministic: same input + same opts => byte-identical output.

Optional deps: none (stdlib only).
"""

from __future__ import annotations

import re

# Lines matching any of these patterns are considered "important".
_IMPORTANT_RE = re.compile(
    r"ERROR|FATAL|CRITICAL|WARN|Exception|Traceback",
    re.IGNORECASE,
)

# Minimum number of lines before we treat input as a "real" log file.
_MIN_LOG_LINES = 5


def compress_logs(
    content: str,
    *,
    stash=None,
    context: int = 2,
    **opts,
) -> str:
    """Return a severity-filtered, deduplicated view of *content*.

    Parameters
    ----------
    content:
        Raw log text (newline-separated lines).
    stash:
        CCR stash callable (injected by the router).  When provided the full
        original log is stashed and a recovery line is appended.  When
        ``None`` the elision markers are kept but no recovery line is added.
    context:
        Number of lines to keep before and after each important line.
    **opts:
        Ignored -- callers pass a shared bag; unknown keys must not raise.
    """
    try:
        return _compress(content, stash=stash, context=context)
    except Exception:  # pragma: no cover -- belt-and-suspenders
        return content


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

def _compress(content: str, *, stash, context: int) -> str:
    """Core compression logic -- wrapped in a single try/except in compress_logs."""
    if not isinstance(content, str):
        return content  # type: ignore[return-value]

    if not content.strip():
        return content

    lines = content.splitlines(keepends=True)

    # Not enough lines to be a real log -- return unchanged.
    if len(lines) < _MIN_LOG_LINES:
        return content

    # --- Pass 1: collapse identical consecutive runs ---
    deduped = _collapse_repeated(lines)

    # --- Pass 2: severity-aware elision ---
    kept = _elide_unimportant(deduped, context=context)

    # Lossless-recovery contract: the elided view drops noise runs, so it is only
    # safe to return when the full original is recoverable. Stash the original and
    # append a recovery line. If there is no stash, or the stash FAILED (store
    # unwritable), we must NOT hand back an irrecoverable summary — return the
    # original content unchanged. This matters most under PostToolUse auto-compress,
    # where a failed stash would otherwise replace the user's tool output with a
    # lossy summary exactly when recovery is impossible.
    if stash is None:
        return content
    placeholder = None
    try:
        placeholder = stash(content, ctype="log")
    except Exception:
        placeholder = None
    if placeholder is None:
        return content  # stash failed -> stay lossless
    # Ensure we do not double up a trailing newline before the footer.
    if kept and not kept.endswith("\n"):
        kept += "\n"
    kept += f"full log: {placeholder}\n"

    return kept


def _collapse_repeated(lines: list[str]) -> list[str]:
    """Collapse consecutive identical lines into ``line (xN)``."""
    if not lines:
        return lines

    out: list[str] = []
    # Track current run.
    run_line = lines[0]
    run_count = 1

    for line in lines[1:]:
        if line == run_line:
            run_count += 1
        else:
            out.append(_emit_run(run_line, run_count))
            run_line = line
            run_count = 1

    out.append(_emit_run(run_line, run_count))
    return out


def _emit_run(line: str, count: int) -> str:
    """Return the canonical representation of a run of *count* identical lines."""
    if count <= 1:
        return line
    # Append the repetition marker before the line ending (if present).
    if line.endswith("\n"):
        return line[:-1] + f" (x{count})\n"
    return line + f" (x{count})"


def _is_important(line: str) -> bool:
    """Return True if *line* matches a severity/exception keyword."""
    return bool(_IMPORTANT_RE.search(line))


def _elide_unimportant(lines: list[str], *, context: int) -> str:
    """Keep important lines +/- *context* neighbours; elide everything else.

    Returns the compressed text as a single string.
    """
    n = len(lines)

    # Build a boolean mask: True = must keep this line.
    keep = [False] * n
    for i, line in enumerate(lines):
        if _is_important(line):
            # Keep the important line and its context window.
            lo = max(0, i - context)
            hi = min(n, i + context + 1)
            for j in range(lo, hi):
                keep[j] = True

    # If everything is important (or nothing is), handle gracefully.
    # If nothing is important we still do the elision (all lines collapse).

    out_parts: list[str] = []
    i = 0
    while i < n:
        if keep[i]:
            out_parts.append(lines[i])
            i += 1
        else:
            # Find the run of non-kept lines.
            j = i
            while j < n and not keep[j]:
                j += 1
            count = j - i
            out_parts.append(f"... {count} lines elided ...\n")
            i = j

    return "".join(out_parts)
