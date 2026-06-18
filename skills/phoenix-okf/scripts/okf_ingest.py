#!/usr/bin/env python3
"""okf_ingest.py — consume an OKF v0.1 bundle as the cheapest sufficient context.

The point of OKF for a Phoenix run is progressive disclosure: an agent should see *what knowledge
exists* (the index, the type/tag distribution, one-line descriptions) before paying to load any
full document. This reader defaults to that index-first outline and only emits a full concept
body when explicitly asked, so the model pays once for orientation instead of swallowing the
whole bundle.

Consumption is permissive per SPEC §9: unknown `type` values, missing optional fields, and broken
cross-links never cause a failure.

Usage:
    python okf_ingest.py BUNDLE                 # index-first outline (cheap)
    python okf_ingest.py BUNDLE --query Metric  # concepts whose type or a tag matches
    python okf_ingest.py BUNDLE --full a/b.md   # one concept's frontmatter + body
    python okf_ingest.py BUNDLE --json          # machine-readable outline
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from okf_common import RESERVED, iter_concepts, read_concept


def load_concepts(root: Path) -> list[dict]:
    concepts = []
    for path, reserved in iter_concepts(root):
        if reserved:
            continue
        meta, body = read_concept(path)
        meta = meta or {}
        concepts.append({
            "path": path.relative_to(root).as_posix(),
            "type": str(meta.get("type", "(untyped)")),
            "title": str(meta.get("title", path.stem)),
            "description": " ".join(str(meta.get("description", "")).split()),
            "tags": list(meta.get("tags", []) if isinstance(meta.get("tags"), (list, tuple)) else []),
            "resource": meta.get("resource"),
            "_body": body,
        })
    return concepts


def outline(root: Path, concepts: list[dict]) -> dict:
    types = Counter(c["type"] for c in concepts)
    tags = Counter(t for c in concepts for t in c["tags"])
    root_index = root / "index.md"
    declared = None
    if root_index.exists():
        meta, _ = read_concept(root_index)
        if meta:
            declared = meta.get("okf_version")
    return {
        "bundle": str(root),
        "okf_version": declared,
        "concepts": len(concepts),
        "types": dict(types),
        "top_tags": dict(tags.most_common(12)),
        "has_root_index": root_index.exists(),
    }


def print_outline(root: Path, concepts: list[dict], max_n: int) -> None:
    o = outline(root, concepts)
    print(f"# OKF bundle: {o['bundle']}")
    print(f"okf_version: {o['okf_version'] or '(undeclared)'}  |  concepts: {o['concepts']}")
    print("\n## Types")
    for t, n in sorted(o["types"].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {t}: {n}")
    if o["top_tags"]:
        print("\n## Top tags")
        print("  " + ", ".join(f"{t}({n})" for t, n in o["top_tags"].items()))
    print(f"\n## Concepts (first {max_n})")
    for c in concepts[:max_n]:
        desc = c["description"][:120]
        print(f"  [{c['type']}] {c['path']} — {desc}")
    if len(concepts) > max_n:
        print(f"  ... {len(concepts) - max_n} more. Use --query to filter or --max to widen.")
    print("\nNext: `--query <type-or-tag>` to filter, or `--full <path>` to load one concept.")


def print_query(concepts: list[dict], query: str, max_n: int) -> None:
    q = query.lower()
    hits = [c for c in concepts if c["type"].lower() == q or q in [t.lower() for t in c["tags"]]
            or q in c["type"].lower()]
    print(f"# {len(hits)} concept(s) matching '{query}' (by type or tag)\n")
    for c in hits[:max_n]:
        print(f"[{c['type']}] {c['path']}")
        if c["description"]:
            print(f"    {c['description'][:160]}")
        if c["tags"]:
            print(f"    tags: {', '.join(c['tags'])}")
    if len(hits) > max_n:
        print(f"... {len(hits) - max_n} more (raise --max).")


def print_full(root: Path, rel: str) -> int:
    cand = rel if rel.endswith(".md") else rel + ".md"
    path = root / cand
    if not path.exists():
        # Tolerant fallback: match by stem suffix.
        matches = [p for p, _ in iter_concepts(root) if p.as_posix().endswith(cand)]
        if not matches:
            print(f"ERROR: concept not found in bundle: {rel}", file=sys.stderr)
            return 1
        path = matches[0]
    print(path.read_text(encoding="utf-8"))
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest an OKF v0.1 bundle, index-first.")
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--query", help="Filter concepts by type or tag.")
    ap.add_argument("--full", help="Print one concept's full frontmatter + body (bundle-relative path).")
    ap.add_argument("--max", type=int, default=40, help="Max concepts to list (default 40).")
    ap.add_argument("--json", action="store_true", help="Emit the outline as JSON.")
    args = ap.parse_args()

    if not args.bundle.is_dir():
        print(f"ERROR: not a directory: {args.bundle}", file=sys.stderr)
        sys.exit(2)

    if args.full:
        sys.exit(print_full(args.bundle, args.full))

    concepts = load_concepts(args.bundle)

    if args.json:
        print(json.dumps(outline(args.bundle, concepts), indent=2))
        return
    if args.query:
        print_query(concepts, args.query, args.max)
        return
    print_outline(args.bundle, concepts, args.max)


if __name__ == "__main__":
    main()
