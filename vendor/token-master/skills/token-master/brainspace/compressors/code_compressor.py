"""Code / AST compressor — tree-sitter skeletonization (Python + Rust).

Walks top-level and nested definitions, keeps headers (and, for Python, leading
docstrings), and replaces function/method bodies with a single stub line that
optionally stashes the full body for lossless recovery. Type declarations whose
shape *is* the signal — Python class members, Rust struct/enum fields, trait
method signatures — are kept verbatim; only executable bodies are elided.

Languages are described by a small per-language spec (``_LANG_SPECS``) naming the
grammar module to lazy-import and the node types that drive the walk:

  * ``elide``   — definitions whose body block is replaced with a stub
                  (Python ``function_definition``; Rust ``function_item``).
  * ``recurse`` — containers kept verbatim in the header but walked for nested
                  defs (Python ``class_definition``; Rust ``impl_item`` /
                  ``trait_item`` / ``mod_item``).
  * ``wrapper`` — nodes that wrap a def behind leading syntax that must be kept
                  (Python ``decorated_definition``; Rust has none).
  * ``docstring`` — whether a leading string statement inside a body is a
                  docstring to preserve (Python only; Rust doc comments are
                  ``///`` sibling line-comments, kept for free as gap bytes).

Contract rules observed:
  1. Never raise — any parse or import failure returns content unchanged.
  2. str in, str out.
  3. Lossy display, lossless recovery: body text is stashed when stash is
     available; otherwise a plain '<N lines elided>' marker is used (lossless
     enough for measurement contexts where stash is None).
  4. Deterministic: traversal follows source order (tree-sitter preserves it).

Optional deps (lazy-imported inside the function):
  tree-sitter          https://pypi.org/project/tree-sitter/
  tree-sitter-python   https://pypi.org/project/tree-sitter-python/
  tree-sitter-rust     https://pypi.org/project/tree-sitter-rust/
When tree-sitter or the language grammar is absent the module still imports
cleanly and the function degrades to a no-op (returns content unchanged).
"""

from __future__ import annotations

import importlib

# Per-language skeletonization spec. Adding a language is a matter of naming its
# grammar module and the node types that play each structural role — the walk
# itself is language-agnostic.
_LANG_SPECS: dict[str, dict] = {
    "python": {
        "module": "tree_sitter_python",
        "elide": ("function_definition",),
        "recurse": ("class_definition",),
        "wrapper": ("decorated_definition",),
        "docstring": True,
    },
    "rust": {
        "module": "tree_sitter_rust",
        # function_item also covers trait *default* methods (they have a body);
        # function_signature_item (no body) is not listed, so it stays verbatim.
        "elide": ("function_item",),
        "recurse": ("impl_item", "trait_item", "mod_item"),
        "wrapper": (),
        "docstring": False,
    },
}


def compress_code(
    content: str,
    *,
    stash=None,
    lang: str = "python",
    **opts,
) -> str:
    """Return a skeletonized view of *content* (Python source by default).

    Parameters
    ----------
    content:
        Raw source code as a ``str``.
    stash:
        CCR stash callable (injected by the router).  When ``None`` the
        compressor behaves losslessly — bodies are replaced with inline
        ``<N lines elided>`` markers rather than placeholders.
    lang:
        Source language.  ``'python'`` and ``'rust'`` are wired; any other
        value triggers a graceful noop.
    **opts:
        Ignored — callers pass a shared bag; unknown keys must not raise.
    """
    # ------------------------------------------------------------------ guards
    if not isinstance(content, str):
        return content  # type: ignore[return-value]
    if not content.strip():
        return content
    spec = _LANG_SPECS.get(lang.lower())
    if spec is None:
        # Only wired languages are skeletonized; others degrade to noop.
        return content

    # -------------------------------------------------- lazy optional imports
    try:
        from tree_sitter import Language, Parser  # type: ignore[import]
        grammar = importlib.import_module(spec["module"])
    except Exception:
        # tree-sitter or the language grammar absent — noop degrade.
        return content

    # --------------------------------------------------------- build language
    try:
        TS_LANG = Language(grammar.language())
        parser = Parser(TS_LANG)
    except Exception:
        return content

    # ----------------------------------------------------------- parse source
    try:
        src_bytes = content.encode("utf-8", errors="replace")
        tree = parser.parse(src_bytes)
    except Exception:
        return content

    # -------------------------------------------------------- walk + rewrite
    try:
        return _walk(
            src_bytes, tree.root_node, spec,
            stash=stash, indent=0, start=0, end=len(src_bytes),
        )
    except Exception:
        return content


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode(src_bytes: bytes, start: int, end: int) -> str:
    return src_bytes[start:end].decode("utf-8", errors="replace")


def _walk(src_bytes: bytes, container, spec, *, stash, indent: int,
          start: int, end: int) -> str:
    """Walk ``container``'s children in source order, rewriting definition bodies
    and keeping everything else verbatim.

    The gap bytes between consecutive nodes (imports, assignments, blank lines,
    comments, attributes, Rust ``///`` doc comments) are emitted unchanged, so
    they survive without per-language handling. ``start`` is the initial cursor
    (used to skip a body's already-consumed leading docstring); ``end`` is the
    flush boundary (``len(src)`` at the top level, the container's end byte when
    recursing into a body)."""
    parts: list[str] = []
    cursor = start
    interesting = set(spec["elide"]) | set(spec["recurse"]) | set(spec["wrapper"])

    for child in container.children:
        if child.end_byte <= cursor:
            continue  # already consumed (e.g. a leading docstring)
        if child.start_byte > cursor:
            parts.append(_decode(src_bytes, cursor, child.start_byte))
        if child.type in interesting:
            parts.append(_rewrite_node(src_bytes, child, spec, stash=stash, indent=indent))
        else:
            parts.append(_decode(src_bytes, child.start_byte, child.end_byte))
        cursor = child.end_byte

    if cursor < end:
        parts.append(_decode(src_bytes, cursor, end))
    return "".join(parts)


def _rewrite_node(src_bytes: bytes, node, spec, *, stash, indent: int) -> str:
    """Dispatch a single node to the rewriter for its structural role."""
    t = node.type
    if t in spec["elide"]:
        return _rewrite_func(src_bytes, node, spec, stash=stash, indent=indent)
    if t in spec["recurse"]:
        return _rewrite_container(src_bytes, node, spec, stash=stash, indent=indent)
    if t in spec["wrapper"]:
        return _rewrite_wrapper(src_bytes, node, spec, stash=stash, indent=indent)
    # Fallback: keep verbatim.
    return _decode(src_bytes, node.start_byte, node.end_byte)


def _rewrite_wrapper(src_bytes: bytes, node, spec, *, stash, indent: int) -> str:
    """Keep leading wrapper syntax (e.g. Python decorator lines); rewrite the
    inner def/class as a unit."""
    parts: list[str] = []
    inner = None
    inner_types = set(spec["elide"]) | set(spec["recurse"])
    for child in node.children:
        if child.type in inner_types:
            inner = child
        else:
            parts.append(_decode(src_bytes, child.start_byte, child.end_byte))

    if inner is None:
        return _decode(src_bytes, node.start_byte, node.end_byte)

    parts.append(_rewrite_node(src_bytes, inner, spec, stash=stash, indent=indent))
    return "".join(parts)


def _rewrite_func(src_bytes: bytes, node, spec, *, stash, indent: int) -> str:
    """Return a skeletonized function: keep header (+ docstring), stub the body."""
    body_node = node.child_by_field_name("body")
    if body_node is None:
        # No body to elide (e.g. an abstract signature) — keep verbatim.
        return _decode(src_bytes, node.start_byte, node.end_byte)

    # Header: everything from node start up to body start (signature, and for
    # Rust the leading visibility / attributes that are children of the node).
    header = _decode(src_bytes, node.start_byte, body_node.start_byte)

    # Extract function name for stash metadata.
    name_node = node.child_by_field_name("name")
    func_name = (
        _decode(src_bytes, name_node.start_byte, name_node.end_byte)
        if name_node
        else "<anon>"
    )

    # Leading docstring (Python only): the first statement if it is a string
    # expression. Rust documentation lives in sibling ``///`` line comments,
    # which are preserved as gap bytes, so no in-body extraction is needed.
    if spec["docstring"]:
        docstring_text, body_start_byte = _extract_docstring(src_bytes, body_node)
    else:
        docstring_text, body_start_byte = "", body_node.start_byte

    # Body bytes (everything after optional docstring, up to body end).
    body_text = _decode(src_bytes, body_start_byte, body_node.end_byte)

    stub_line = _make_stub(body_text, func_name, stash=stash, indent=indent)

    pieces = [header]
    if docstring_text:
        pieces.append(docstring_text)
    pieces.append(stub_line)
    result = "".join(pieces)
    if not result.endswith("\n"):
        result += "\n"
    return result


def _rewrite_container(src_bytes: bytes, node, spec, *, stash, indent: int) -> str:
    """Return a skeletonized container (Python class, Rust impl/trait/mod): keep
    the header (+ docstring), recurse into the body rewriting each method."""
    body_node = node.child_by_field_name("body")
    if body_node is None:
        return _decode(src_bytes, node.start_byte, node.end_byte)

    # Header: up to the body opener (``class X:`` / ``impl T for X {``).
    header = _decode(src_bytes, node.start_byte, body_node.start_byte)

    if spec["docstring"]:
        docstring_text, body_start_byte = _extract_docstring(src_bytes, body_node)
    else:
        docstring_text, body_start_byte = "", body_node.start_byte

    body = _walk(
        src_bytes, body_node, spec,
        stash=stash, indent=indent + 4,
        start=body_start_byte, end=body_node.end_byte,
    )

    pieces = [header]
    if docstring_text:
        pieces.append(docstring_text)
    pieces.append(body)
    return "".join(pieces)


def _extract_docstring(src_bytes: bytes, body_node) -> tuple[str, int]:
    """Return (docstring_source_text, next_byte) for the leading docstring.

    If no docstring is present, returns ('', body_node.start_byte).
    """
    for child in body_node.children:
        if child.type in ("comment", "newline", "\n"):
            continue
        if child.type == "expression_statement":
            # Check if sole meaningful child is a string
            string_child = _first_string_child(child)
            if string_child is not None:
                text = _decode(src_bytes, child.start_byte, child.end_byte)
                return text, child.end_byte
        # First non-docstring child: stop
        break
    return "", body_node.start_byte


def _first_string_child(node):
    """Return the first string node child (or None) of an expression_statement."""
    for child in node.children:
        if child.type in ("string", "concatenated_string"):
            return child
        if child.type not in ("comment", "newline", "\n"):
            return None
    return None


def _make_stub(body_text: str, name: str, *, stash, indent: int) -> str:
    """Return the stub replacement line for a function body.

    Uses stash when available; falls back to a plain elision marker.
    """
    n_lines = body_text.count("\n") + (1 if body_text and not body_text.endswith("\n") else 0)
    pad = " " * (indent + 4)  # one extra indent level inside the function

    if stash is not None:
        placeholder = None
        try:
            placeholder = stash(body_text, ctype="code", source=f"{name} body")
        except Exception:
            placeholder = None
        if placeholder is not None:
            return f"{pad}... {placeholder}\n"
        # stash returned None — keep losslessly with inline marker
    # Lossless fallback (no stash, or stash failed)
    return f"{pad}... <{n_lines} lines elided>\n"
