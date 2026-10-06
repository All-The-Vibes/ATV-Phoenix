"""ContentRouter — detect content type and dispatch to the right compressor.

The router is the engine's front door. It runs cheap, high-precision checks first
(an explicit hint from the caller, then a JSON parse), then heuristics (logs by
line shape, code by keywords+structure), and finally falls back to prose. Prose is
the weakest, most expensive lever, so it is the last resort, never the default.

Every compressor is lazy-imported the first time its type is selected, mirroring
graphify_mcp.py: the module imports cleanly even if tree-sitter / llmlingua are
absent, and a compressor that cannot load degrades to ``noop`` (return input
unchanged). The router itself never raises.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Optional

from .compressors import noop


class ContentType(str, Enum):
    JSON = "json"
    CODE = "code"
    LOG = "log"
    PROSE = "prose"


# --- detection ----------------------------------------------------------------

_CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c",
              ".cpp", ".h", ".hpp", ".rb", ".php", ".cs", ".kt", ".swift")
# File extensions whose source the code compressor can skeletonize today. The
# extension is the reliable language signal (same philosophy as hint-first
# content detection), so language is resolved from it rather than sniffed from
# content. Extensions outside this map route to CODE but compress as a no-op
# until their grammar is wired into code_compressor._LANG_SPECS.
_LANG_BY_EXT = {
    ".py": "python",
    ".pyi": "python",
    ".rs": "rust",
}
_LOG_LINE_RE = re.compile(
    r"^\s*(\d{4}-\d\d-\d\d|\d\d:\d\d:\d\d|\[?(?:INFO|WARN|WARNING|ERROR|DEBUG|TRACE|FATAL|CRITICAL))",
    re.IGNORECASE | re.MULTILINE,
)
_CODE_KW_RE = re.compile(r"\b(def|class|function|func|fn|import|package|public|private)\b")


def detect(content: str, hint: Optional[str] = None) -> ContentType:
    """Classify ``content``. ``hint`` is a tool name or filename when available —
    it is the cheapest, most reliable signal, so it wins first."""
    if hint:
        h = hint.lower()
        # Prose docs first: markdown/rST contain code-fence keywords (import, def,
        # function) that would otherwise trip the CODE heuristic below. The filename
        # is the reliable signal — a .md file is prose with embedded code, not code.
        if h.endswith((".md", ".markdown", ".rst", ".adoc")):
            return ContentType.PROSE
        if h.endswith(_CODE_EXTS):
            return ContentType.CODE
        if h.endswith(".json"):
            return ContentType.JSON
        if h.endswith((".log", ".txt")) or h in ("test", "build", "pytest", "lint"):
            return ContentType.LOG

    s = content.lstrip()
    # JSON: cheap structural sniff before a full parse attempt.
    if s[:1] in "{[":
        try:
            json.loads(content)
            return ContentType.JSON
        except (ValueError, TypeError):
            pass

    # Logs: many lines that look like timestamped/leveled records.
    if len(_LOG_LINE_RE.findall(content)) >= 5:
        return ContentType.LOG

    # Code: structural keywords plus enough lines to be a file, not a sentence.
    if content.count("\n") > 3 and _CODE_KW_RE.search(content):
        return ContentType.CODE

    return ContentType.PROSE


def lang_from_hint(hint: Optional[str]) -> Optional[str]:
    """Resolve a source language from a filename/tool-name ``hint`` (its
    extension), or ``None`` when the hint carries no recognized code extension.

    This is what lets the code compressor skeletonize the right grammar: without
    it every CODE output would be parsed as the ``compress_code`` default
    (Python), so a ``.rs`` read would silently no-op."""
    if not hint:
        return None
    h = hint.lower()
    for ext, lang in _LANG_BY_EXT.items():
        if h.endswith(ext):
            return lang
    return None


# --- dispatch (lazy, fail-safe) -----------------------------------------------

def _load(ctype: ContentType):
    """Return the compressor callable for a type, or ``noop`` if it can't load."""
    try:
        if ctype is ContentType.JSON:
            from .compressors.json_compressor import compress_json
            return compress_json
        if ctype is ContentType.CODE:
            from .compressors.code_compressor import compress_code
            return compress_code
        if ctype is ContentType.LOG:
            from .compressors.logs_compressor import compress_logs
            return compress_logs
        if ctype is ContentType.PROSE:
            from .compressors.prose_compressor import compress_prose
            return compress_prose
    except Exception:
        return noop
    return noop


def route(content: str, hint: Optional[str] = None, *, stash=None, **opts) -> str:
    """Detect the type of ``content`` and run the matching compressor.

    Never raises: a compressor that fails for any reason falls back to returning
    the content unchanged. ``stash`` and ``opts`` are forwarded to the compressor.
    Never expands: if a compressor's output is not smaller than the input (common
    on tiny snippets, where placeholder/footer overhead dominates), the original is
    returned — compression must never cost tokens.
    """
    out, _ = route_typed(content, hint, stash=stash, **opts)
    return out


def route_typed(content: str, hint: Optional[str] = None, *, stash=None, **opts):
    """Like :func:`route` but also returns the detected ``ContentType`` (for the
    MCP server's reporting). Returns ``(compressed, content_type)``.

    Enforces the never-expand invariant centrally so every caller (MCP tool,
    PostToolUse hook, direct use) is protected: a result that is not strictly
    smaller than the input is discarded in favor of the original.

    The invariant is measured in *tokens*, not characters, because tokens are the
    real cost. The distinction is not academic: a content-addressed placeholder
    like ``[[BR:0fd4e3ad3d2b|code; some_long_function_name body; 3L]]`` can be
    fewer characters than the body it replaces while tokenizing to *more* tokens
    (random hex hashes and long identifiers do not BPE-merge). A char-based guard
    would wave that through and silently cost tokens — the exact thing this guard
    exists to forbid. We still short-circuit on the cheap char check first: if the
    output is not even shorter in characters, it cannot be a win, so we skip the
    tokenizer call.
    """
    if not content:
        return content, ContentType.PROSE
    try:
        ctype = detect(content, hint)
        # For code, resolve the language from the hint's extension and pass it to
        # the compressor (which otherwise defaults to Python). An explicit caller
        # ``lang`` wins; an unrecognized extension leaves it unset (compressor
        # default), so behavior is unchanged for already-supported inputs.
        if ctype is ContentType.CODE and "lang" not in opts:
            lang = lang_from_hint(hint)
            if lang:
                opts = {**opts, "lang": lang}
        out = _load(ctype)(content, stash=stash, **opts)
        if not isinstance(out, str) or len(out) >= len(content):
            return content, ctype  # cheap reject: not even char-smaller
        # Char-smaller but we bill in tokens — confirm it is token-smaller too.
        from .tokens import estimate
        if estimate(out) >= estimate(content):
            return content, ctype  # never expand in the unit that actually costs
        return out, ctype
    except Exception:
        return content, ContentType.PROSE
