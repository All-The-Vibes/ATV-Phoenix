#!/usr/bin/env python
"""Brainspace PostToolUse hook — the auto-compress half, at the append boundary.

This is the piece an MCP server structurally cannot be: blanket, automatic
compression of tool output *before* it is appended to the transcript and cached.
MCP tools are model-invoked (they fire only when the model elects to call them),
and by then the raw output is already in context. A PostToolUse hook runs at the
moment the host has a tool result in hand but has not yet committed it, so it is
the correct — and only — place to compress every output once, deterministically,
before it can perturb the provider's prompt-cache prefix.

THE CACHE-SAFETY RULE this hook exists to honor: compress each piece of content
exactly once, here, at first entry. Never rewrite history. Because the CCR
placeholder is a deterministic function of the content, the compressed block is
byte-identical on every future turn, so it never changes the cumulative prefix
hash that Anthropic/OpenAI prompt caching depends on.

Contract (Claude Code PostToolUse hooks — verified against code.claude.com/docs/en/hooks):
  * stdin: a JSON object describing the tool call + its result.
  * stdout: a JSON object, processed ONLY on exit 0. To REPLACE what the model
    sees, emit ``hookSpecificOutput`` with ``hookEventName: "PostToolUse"`` and
    ``updatedToolOutput`` (the documented field that "replaces the tool's result").
    stdout must contain ONLY that JSON — no extra text.
  * Host stdout cap: hook output is capped at 10,000 chars; anything larger is
    spilled to a file and replaced with a preview. A *compression* hook must
    therefore guarantee its replacement lands UNDER the cap, or the host re-truncates
    it and the recoverable-placeholder footer is lost. We enforce this explicitly:
    if the compressed text would exceed the cap we stash the whole original and
    return a compact placeholder-only result instead.
  * Failure policy: ANY error, or nothing gained → emit nothing, exit 0 (the docs'
    "no decision": original output is used). A compression hook must be invisible
    when it cannot help.

Configurable via env:
  * BRAINSPACE_HOOK_MIN_CHARS — only compress outputs larger than this (default 800).
  * BRAINSPACE_HOOK_TOOLS — comma-separated allowlist of tool names to compress
    (default: a sensible set of read/exec tools). "*" means all.

Run by the host as: uv run --with mcp --with tree-sitter --with tree-sitter-python
                        --with tree-sitter-rust --with tiktoken python brainspace_posttooluse.py
                    (grammars enable code skeletonization; brainspace_setup.py wires them in.)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Resolve `import brainspace` regardless of the host's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_CHARS = int(os.environ.get("BRAINSPACE_HOOK_MIN_CHARS", "800"))
# Host caps hook stdout at 10k chars; stay safely under so our replacement (and its
# recoverable footer) is never re-truncated by the host.
STDOUT_CAP = int(os.environ.get("BRAINSPACE_HOOK_STDOUT_CAP", "9000"))
_TOOLS_ENV = os.environ.get("BRAINSPACE_HOOK_TOOLS", "Bash,Read,Grep,Glob,WebFetch,view,read,execute,search")
_TOOL_ALLOW = {t.strip() for t in _TOOLS_ENV.split(",") if t.strip()}


def _noop_exit():
    """Emit nothing and succeed — the safe degrade for every failure path."""
    sys.exit(0)


def _extract(payload: dict):
    """Pull (tool_name, output_text, output_key) from the host's PostToolUse JSON.

    Claude Code nests the result under ``tool_response``; some shapes use
    ``tool_result``/``output``. We read defensively and report which key held the
    text so we can write the replacement back into the same shape.
    """
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    resp = payload.get("tool_response", payload.get("tool_result", payload.get("output")))
    # tool_response may be a plain string or a dict carrying the text.
    if isinstance(resp, str):
        return tool_name, resp, ("tool_response", None)
    if isinstance(resp, dict):
        for k in ("content", "output", "stdout", "text"):
            v = resp.get(k)
            if isinstance(v, str) and v:
                return tool_name, v, ("tool_response", k)
    return tool_name, None, (None, None)


def _file_hint(payload: dict) -> str | None:
    """Return the file path from the tool *input*, when the tool acts on a file.

    The router's hint is its strongest signal: a path's extension drives both
    content-type detection and code-language resolution (``.rs`` → Rust). For a
    Read of ``foo.rs`` the tool name alone (``"Read"``) carries neither, so we
    prefer the input path and fall back to the tool name when there is none."""
    ti = payload.get("tool_input") or payload.get("toolInput") or payload.get("input")
    if isinstance(ti, dict):
        for k in ("file_path", "filePath", "path", "notebook_path"):
            v = ti.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw:
            _noop_exit()
        payload = json.loads(raw)
    except (ValueError, OSError):
        _noop_exit()

    try:
        tool_name, text, _key = _extract(payload)
        if not text or len(text) < MIN_CHARS:
            _noop_exit()
        if "*" not in _TOOL_ALLOW and tool_name and tool_name not in _TOOL_ALLOW:
            _noop_exit()

        # Compress with the CCR stash wired in, so the original is recoverable via
        # brainspace_retrieve. Lazy imports: a missing dep => no-op, never a crash.
        from brainspace.ccr import CCR
        from brainspace.router import route_typed
        from brainspace import tokens

        ccr = CCR()
        # Prefer the input file path as the routing hint (its extension resolves
        # both content type and code language); fall back to the tool name.
        hint = _file_hint(payload) or (tool_name or None)
        compressed, ctype = route_typed(text, hint, stash=ccr.stash)
        if compressed == text or len(compressed) >= len(text):
            _noop_exit()  # nothing gained — leave the output untouched

        rep = tokens.reduction(text, compressed)
        note = (
            f"{compressed}\n\n— brainspace[{ctype.value}] auto-compressed "
            f"{rep['tokens_before']}→{rep['tokens_after']} tok ({rep['pct_reduction']}%); "
            f"brainspace_retrieve to expand —"
        )

        # Enforce the host's 10k stdout cap. If our replacement is still too big,
        # stash the WHOLE original and return a compact placeholder-only result, so
        # the model always gets a recoverable reference instead of a host-truncated
        # blob with the footer chopped off.
        if len(note) > STDOUT_CAP:
            ref = ccr.stash(text, ctype=ctype.value, source=tool_name or "tool output")
            if ref:
                note = (
                    f"— brainspace[{ctype.value}]: output too large to inline "
                    f"({len(text):,} chars); stashed. Expand with brainspace_retrieve {ref} —"
                )
            else:
                _noop_exit()  # could not stash → must not lose data; keep original

        # PostToolUse output-rewriting contract (verified field name).
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": note,
            }
        }
        sys.stdout.write(json.dumps(out))
        sys.exit(0)
    except Exception:
        _noop_exit()


if __name__ == "__main__":
    main()
