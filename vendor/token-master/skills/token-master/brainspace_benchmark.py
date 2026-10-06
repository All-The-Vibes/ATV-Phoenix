#!/usr/bin/env python
"""Brainspace benchmark launcher — measure compression on your own content.

Thin entry point (mirrors brainspace_mcp.py / brainspace_posttooluse.py): it makes the
sibling ``brainspace`` package importable when the host launches this file by absolute
path from an arbitrary working directory, then delegates to ``brainspace.benchmark``.

Quick start (from the installed location, ``<host-home>/token-master/``)::

    # Benchmark your own files:
    uv run --with mcp --with tiktoken python brainspace_benchmark.py path/to/file.json server.log

    # Benchmark a directory (type auto-detected per file):
    uv run --with mcp --with tiktoken python brainspace_benchmark.py ./logs

    # Benchmark piped output:
    pytest -v | uv run --with mcp --with tiktoken python brainspace_benchmark.py --stdin --hint=pytest

    # No args → instant demo over Brainspace's own files.
    uv run --with mcp --with tiktoken python brainspace_benchmark.py

Add ``--json`` for machine-readable output, ``--turns N`` for the area-under-curve
horizon, ``--max-files N`` to widen the directory cap. ``tiktoken`` gives accurate
token counts (falls back to a heuristic if absent); add ``--with tree-sitter
--with tree-sitter-python`` for the code compressor.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brainspace.benchmark import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
