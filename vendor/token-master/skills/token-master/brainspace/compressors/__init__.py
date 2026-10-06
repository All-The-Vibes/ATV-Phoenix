"""The compressor contract.

Every compressor is a callable with this exact signature::

    def compress(content: str, *, stash: StashFn | None = None, **opts) -> str

Hard rules (enforced by the test suite, relied on by the router and MCP server):

1.  **Never raise.** A compressor that hits anything it cannot handle returns the
    input unchanged (a no-op compression is always safe). The whole point of the
    layer is to be invisible when it cannot help — never to break the host.
2.  **Pure text in, text out.** Content arrives as a ``str`` and leaves as a
    ``str``. Closed token-only APIs (Claude, Copilot) cannot carry anything else.
3.  **Lossy display, lossless recovery.** A compressor may drop detail from what
    the model *sees*, but only if it first hands the original to ``stash`` and
    embeds the returned placeholder. ``stash(original, ...)`` returns a stable
    ``<<hr:HASH|meta>>`` token the model can pass to ``brainspace_retrieve`` to get
    the full content back. If ``stash`` is ``None`` the compressor must stay
    lossless (used in measurement / no-CCR contexts).
4.  **Deterministic.** Same input + same options + same stash ⇒ same output,
    byte for byte. This is what keeps provider prompt-cache prefixes stable.

``opts`` is compressor-specific (e.g. ``rate`` for prose, ``sample`` for JSON).
Unknown options must be ignored, not rejected — callers pass a shared bag.
"""

from __future__ import annotations

from typing import Callable, Protocol

# A stash function takes the original content plus light metadata and returns a
# stable placeholder string. Provided by the CCR store; injected so compressors
# never import the store directly (keeps them unit-testable in isolation).
StashFn = Callable[..., str]


class Compressor(Protocol):
    """Structural type for a compressor. Implementations are plain functions."""

    def __call__(self, content: str, *, stash: StashFn | None = None, **opts) -> str:
        ...


def noop(content: str, *, stash: StashFn | None = None, **opts) -> str:
    """The identity compressor — the safe fallback for unknown content.

    Also the reference implementation of the contract: it never raises, returns
    text, is lossless, and is deterministic.
    """
    return content
