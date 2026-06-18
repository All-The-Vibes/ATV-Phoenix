#!/usr/bin/env python3
"""okf_freshness.py — sense whether an exported OKF bundle is still in sync with its source graph.

A committed code-graph bundle (e.g. `examples/okf-code-graph/`) is a derived artifact: it can
silently drift after the underlying `graph.json` is rebuilt. This check compares the
`built_at_commit` anchored in the bundle's root `index.md` against the `built_at_commit` of the
current `graph.json`.

  exit 0  -> FRESH   (commits match, or graph has no commit to compare)
  exit 1  -> STALE   (commits differ — re-run okf_export)
  exit 2  -> ERROR   (bundle/graph missing or unreadable)

Designed to be driven by the Phoenix spine as a `command_exit` sense check, so bundle staleness
becomes an objective red signal a run can heal (rebuild) instead of trusting stale knowledge.

Usage:
    python okf_freshness.py BUNDLE_DIR [--graph .token-master/graph.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from okf_common import read_concept


def bundle_commit(bundle: Path) -> str | None:
    idx = bundle / "index.md"
    if not idx.exists():
        return None
    meta, _ = read_concept(idx)
    if not meta:
        return None
    val = meta.get("built_at_commit")
    return str(val) if val else None


def graph_commit(graph: Path) -> str | None:
    data = json.loads(graph.read_text(encoding="utf-8"))
    val = data.get("built_at_commit")
    return str(val) if val else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Sense whether an OKF bundle is fresh vs its source graph.")
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--graph", default=".token-master/graph.json", type=Path)
    args = ap.parse_args()

    if not args.bundle.is_dir():
        print(f"ERROR: bundle not found: {args.bundle}", file=sys.stderr)
        sys.exit(2)
    if not args.graph.is_file():
        print(f"ERROR: graph not found: {args.graph}", file=sys.stderr)
        sys.exit(2)

    b = bundle_commit(args.bundle)
    g = graph_commit(args.graph)

    if b is None:
        print(f"ERROR: bundle root index.md has no built_at_commit anchor ({args.bundle}/index.md)",
              file=sys.stderr)
        sys.exit(2)
    if g is None:
        print(f"FRESH (graph {args.graph} declares no built_at_commit; nothing to compare)")
        sys.exit(0)

    if b == g:
        print(f"FRESH: bundle and graph at commit {b[:12]}")
        sys.exit(0)
    print(f"STALE: bundle at {b[:12]} but graph at {g[:12]} — re-run okf_export.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
