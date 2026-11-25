"""Brainspace — the context-compression layer that complements TokenMaster routing.

TokenMaster *eliminates* re-reads by routing structural questions to a prebuilt
code graph. Brainspace *shrinks* the content that still enters the context window —
tool outputs, file reads, logs, RAG chunks — so the tokens TokenMaster does not
remove are at least cheap.

The two act on near-disjoint token populations, so they compound rather than
compete. The one rule that keeps them from colliding at the provider's prompt
cache: compress each piece of content exactly once, at the moment it first enters
context, with a STABLE content-addressed placeholder — never rewrite history.
(Rewriting a block that is already in the cached prefix changes the cumulative
prefix hash and evicts everything after it.)

Public surface:
  * ``compressors.Compressor`` — the protocol every compressor implements.
  * ``ccr.CCR`` — the content-addressed reversible store of originals.
  * ``router.route`` — detect content type and dispatch to the right compressor.
  * ``tokens.estimate`` — a token-count proxy for measuring reduction.

Design rules inherited from the TokenMaster codebase (see graphify_mcp.py):
  * Never raise out of a tool/compressor path — degrade to a clear value instead.
  * Lazy-import heavy/optional backends (tree-sitter, llmlingua) so the server
    registers cleanly even when they are absent.
  * UTF-8 everywhere; resolve paths so one install serves every repo.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
