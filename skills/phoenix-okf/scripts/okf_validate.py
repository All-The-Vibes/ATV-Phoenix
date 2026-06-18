#!/usr/bin/env python3
"""okf_validate.py — check a directory for OKF v0.1 conformance (SPEC.md S9).

A bundle is conformant if:
  1. Every non-reserved `.md` file contains a parseable YAML frontmatter block.
  2. Every frontmatter block contains a non-empty `type` field.
  3. Reserved filenames (`index.md`, `log.md`) follow their structural rules:
     - `index.md` carries NO frontmatter, EXCEPT a bundle-root `index.md` which MAY declare
       `okf_version`.
     - `log.md` date headings use ISO 8601 `YYYY-MM-DD`.

Per S9 the consumption model is permissive: missing optional fields, unknown `type` values,
extra frontmatter keys, and broken cross-links are NOT errors (some are reported as warnings).

Exit code 0 = conformant (this is the phoenix_sense gate); 1 = one or more errors.

Usage:
    python okf_validate.py BUNDLE_DIR [--strict-links]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from okf_common import RESERVED, iter_concepts, read_concept

DATE_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)


def _strip_code(body: str) -> str:
    """Drop fenced code blocks so illustrative links inside examples are not scanned."""
    return FENCE_RE.sub("", body)


def validate(root: Path, strict_links: bool = False) -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []
    concept_paths: set[str] = set()
    types: dict[str, int] = {}
    n_concepts = 0

    is_root_index = lambda p: p.name == "index.md" and p.parent.resolve() == root.resolve()

    for path, reserved in iter_concepts(root):
        relp = path.relative_to(root).as_posix()
        if reserved:
            meta, body = read_concept(path)
            if path.name == "index.md":
                if is_root_index(path):
                    # Root index MAY carry frontmatter; allow OKF + freshness-anchor keys.
                    allowed = {"okf_version", "title", "okf_source", "generated_at", "built_at_commit"}
                    if meta is not None and meta and set(meta) - allowed:
                        warnings.append(f"{relp}: unexpected root index.md frontmatter keys: {sorted(set(meta) - allowed)}")
                elif meta is not None and meta:
                    errors.append(f"{relp}: index.md must not carry frontmatter (only the bundle-root index may)")
            elif path.name == "log.md":
                headings = [m.group(1) for line in body.splitlines() if (m := DATE_RE.match(line.strip()))]
                bad = [line for line in body.splitlines()
                       if line.strip().startswith("## ") and not DATE_RE.match(line.strip())]
                if bad:
                    errors.append(f"{relp}: log.md date heading not ISO 8601 YYYY-MM-DD: {bad[0]!r}")
            continue

        # Non-reserved => concept document.
        n_concepts += 1
        concept_paths.add(relp)
        meta, _ = read_concept(path)
        if meta is None:
            errors.append(f"{relp}: no parseable YAML frontmatter block (S9.1)")
            continue
        t = meta.get("type")
        if t is None or str(t).strip() == "":
            errors.append(f"{relp}: missing or empty required `type` field (S9.2)")
        else:
            types[str(t)] = types.get(str(t), 0) + 1

    # Cross-link check: broken links are tolerated by spec (warning unless --strict-links).
    broken = 0
    for path, reserved in iter_concepts(root):
        if reserved and path.name != "log.md":
            continue
        _, body = read_concept(path)
        for m in LINK_RE.finditer(_strip_code(body)):
            target = m.group(1).strip()
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if target.startswith("/"):
                resolved = target.lstrip("/")
            else:
                resolved = (path.parent.relative_to(root) / target).as_posix()
            # Normalize ./ and trailing slash (directory link -> its index.md)
            resolved = re.sub(r"^\./", "", resolved)
            cand = resolved + "index.md" if resolved.endswith("/") else resolved
            cand = cand.lstrip("/")
            if cand.endswith(".md") and cand not in concept_paths and not (root / cand).exists():
                broken += 1
                msg = f"{path.relative_to(root).as_posix()}: link target not found: {target}"
                (errors if strict_links else warnings).append(msg)

    stats = {"concepts": n_concepts, "types": types, "broken_links": broken}
    return errors, warnings, stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate an OKF v0.1 bundle for conformance.")
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--strict-links", action="store_true",
                    help="Treat broken cross-links as errors (spec default: tolerated).")
    args = ap.parse_args()

    if not args.bundle.is_dir():
        print(f"ERROR: not a directory: {args.bundle}", file=sys.stderr)
        sys.exit(2)

    errors, warnings, stats = validate(args.bundle, args.strict_links)

    print(f"OKF conformance report for {args.bundle}/")
    print(f"  concept documents : {stats['concepts']}")
    print(f"  type values       : {', '.join(f'{k}x{v}' for k, v in sorted(stats['types'].items())) or '(none)'}")
    print(f"  broken links      : {stats['broken_links']} (tolerated per S9 unless --strict-links)")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")

    if errors:
        print(f"\nNON-CONFORMANT: {len(errors)} error(s).")
        sys.exit(1)
    print("\nCONFORMANT with OKF v0.1.")
    sys.exit(0)


if __name__ == "__main__":
    main()

