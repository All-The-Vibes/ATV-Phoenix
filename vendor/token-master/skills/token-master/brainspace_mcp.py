#!/usr/bin/env python
"""Brainspace compression MCP server.

The model-invoked half of the Brainspace layer. It exposes three tools so the host
CLI can shrink and recover content on demand:

  * ``brainspace_compress(content, hint="")`` — detect the content type and compress,
    stashing the original in the CCR store so nothing is lost.
  * ``brainspace_retrieve(ref)`` — expand a ``[[BR:...]]`` placeholder back to the
    exact original content.
  * ``brainspace_stats()`` — report store size, dedup ratio, and retrieval counts.

Why an MCP server (and what it cannot do): MCP tools are *model-controlled* — they
run only when the model chooses to call them. That makes this server the right home
for the inherently model-invoked ``brainspace_retrieve`` escape hatch and for
explicit compression requests. It CANNOT transparently compress every tool output
the way a proxy can — blanket auto-compression belongs in the PostToolUse hook
(brainspace_posttooluse.py), which runs at the append boundary before content is
ever cached. The two together are the full layer; this file is the model-facing
part, deliberately scoped.

Design mirrors graphify_mcp.py:
  * Lazy CCR construction on first tool call (server registers cleanly with no store).
  * Tools return clear diagnostic strings on failure instead of raising.
  * Output is capped so the server never blows the token budget it exists to protect.

Run: uv run --with mcp --with tree-sitter --with tree-sitter-python \
         --with tree-sitter-rust --with tiktoken python brainspace_mcp.py
     (the tree-sitter grammars enable code skeletonization; without them the
     code compressor degrades to a no-op. brainspace_setup.py wires these in.)
"""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Make `import brainspace` resolve when the host launches this file by absolute path
# from an arbitrary working directory (the installer copies it next to the package).
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))

from brainspace.ccr import CCR  # noqa: E402
from brainspace.router import route_typed  # noqa: E402
from brainspace import tokens  # noqa: E402

# Optional cap so a single compress call cannot itself return a huge blob.
MAX_RETRIEVE_CHARS = int(os.environ.get("BRAINSPACE_MAX_RETRIEVE", "200000"))

_STATE = {"ccr": None}


def _ccr() -> CCR:
    """Lazy-construct the CCR store on first use (honors BRAINSPACE_CCR env)."""
    if _STATE["ccr"] is None:
        _STATE["ccr"] = CCR()
    return _STATE["ccr"]


mcp = FastMCP("brainspace")


@mcp.tool()
def brainspace_compress(content: str, hint: str = "") -> str:
    """Compress a blob of content (tool output, file, log, JSON, or prose) before
    putting it in context, and stash the original so it can be recovered.

    Pass ``hint`` as the source filename or tool name when you have it (e.g.
    "server.py" or "pytest") — it improves content-type detection. The compressed
    text may contain ``[[BR:...]]`` placeholders; call ``brainspace_retrieve`` with
    one to get that original back. Returns the compressed text with a one-line
    savings footer."""
    if not content:
        return content
    try:
        ccr = _ccr()
        compressed, ctype = route_typed(content, hint or None, stash=ccr.stash)
        # No-op when nothing was gained: route_typed returns the input unchanged for
        # small/non-compressible content or when optional compressors are missing.
        # Appending a savings footer there would grow the transcript and falsely
        # imply a [[BR:]] placeholder exists to expand. Mirror the PostToolUse hook
        # and return the content untouched.
        if compressed == content:
            return content
        rep = tokens.reduction(content, compressed)
        footer = (
            f"\n\n— brainspace[{ctype.value}]: {rep['tokens_before']}→{rep['tokens_after']} tok "
            f"({rep['pct_reduction']}% via {rep['backend']}); expand with brainspace_retrieve —"
        )
        return compressed + footer
    except Exception as exc:  # never raise out of a tool
        return f"{content}\n\n— brainspace: compression skipped ({type(exc).__name__}) —"


@mcp.tool()
def brainspace_retrieve(ref: str) -> str:
    """Expand a Brainspace placeholder back to its full original content.

    ``ref`` is a ``[[BR:<hash>|...]]`` token (or just the hash) that appeared in a
    compressed result. Use this when a compressed view elided a detail you now
    need. Returns the exact original content, or a clear message if it is unknown
    (it may have been evicted between sessions — re-read the source if so)."""
    try:
        original = _ccr().retrieve(ref)
        if original is None:
            return (
                f"No stored original for '{ref.strip()}'. It may have been evicted "
                "between sessions — re-read the source directly."
            )
        if len(original) > MAX_RETRIEVE_CHARS:
            head = original[:MAX_RETRIEVE_CHARS]
            return f"{head}\n\n… (truncated at {MAX_RETRIEVE_CHARS} chars of {len(original)})"
        return original
    except Exception as exc:
        return f"brainspace_retrieve failed ({type(exc).__name__})."


@mcp.tool()
def brainspace_stats() -> str:
    """Report Brainspace cache stats: number of stored originals, on-disk vs original
    bytes (storage compression), total retrievals, and the store path."""
    try:
        s = _ccr().stats()
        if s.get("error"):
            return f"brainspace store at {s.get('db_path')}: unreadable."
        ratio = s.get("compression_ratio")
        ratio_str = f"{ratio}x" if ratio else "n/a"
        return (
            f"brainspace CCR store:\n"
            f"  entries:        {s['entries']}\n"
            f"  original bytes: {s['original_bytes']:,}\n"
            f"  stored bytes:   {s['stored_bytes']:,} ({ratio_str} on disk)\n"
            f"  retrievals:     {s['total_retrievals']}\n"
            f"  path:           {s['db_path']}"
        )
    except Exception as exc:
        return f"brainspace_stats failed ({type(exc).__name__})."


if __name__ == "__main__":
    mcp.run()
