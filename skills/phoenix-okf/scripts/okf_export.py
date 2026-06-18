#!/usr/bin/env python3
"""okf_export.py — turn a graphify/TokenMasterX `graph.json` into an OKF v0.1 knowledge bundle.

Phoenix's Context Assembly pillar keeps its code knowledge in `.token-master/graph.json`, an
opaque blob no human reviews and no other tool reads. This exporter renders that same knowledge
as a conformant Open Knowledge Format bundle: a directory of markdown documents with YAML
frontmatter that git can diff, Obsidian can browse, and any agent can ingest verbatim.

Granularity: one concept document per **source file** (diffable and human-meaningful), with the
file's symbols in the body and cross-file graph edges expressed as bundle-relative markdown
links. INFERRED edges are flagged as candidates, honoring phoenix-context's honesty rule that
graphify call edges are ~0.8-confidence candidates, not a verified call graph.

Usage:
    python okf_export.py [--graph PATH] [--out DIR] [--name NAME]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from okf_common import dump_frontmatter, write_concept

EXT_TYPE = {
    ".rs": "Rust Source",
    ".py": "Python Source",
    ".js": "JavaScript Source",
    ".ts": "TypeScript Source",
    ".go": "Go Source",
    ".java": "Java Source",
    ".rb": "Ruby Source",
    ".c": "C Source",
    ".h": "C Header",
    ".cpp": "C++ Source",
    ".md": "Markdown Document",
    ".json": "JSON Config",
    ".toml": "TOML Config",
    ".yaml": "YAML Config",
    ".yml": "YAML Config",
    ".sh": "Shell Script",
    ".ps1": "PowerShell Script",
    ".sql": "SQL Source",
    ".txt": "Text Document",
}
FILETYPE_TYPE = {"code": "Code File", "document": "Document", "rationale": "Rationale"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def concept_relpath(source_file: str) -> str:
    """Bundle-relative path of the concept doc for a repo source file (always under concepts/)."""
    norm = source_file.replace("\\", "/").lstrip("/")
    return f"concepts/{norm}.md"


def derive_type(source_file: str, file_types: set[str]) -> str:
    ext = Path(source_file).suffix.lower()
    if ext in EXT_TYPE:
        return EXT_TYPE[ext]
    for ft in ("code", "document", "rationale"):
        if ft in file_types:
            return FILETYPE_TYPE[ft]
    return "Concept"


def build(graph_path: Path, out_dir: Path, name: str) -> dict:
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))
    built_at = data.get("built_at_commit")
    ts = now_iso()

    node_by_id = {n["id"]: n for n in nodes}
    file_of = {n["id"]: n.get("source_file", "(unknown)") for n in nodes}

    nodes_by_file: dict[str, list] = defaultdict(list)
    for n in nodes:
        nodes_by_file[n.get("source_file", "(unknown)")].append(n)

    # Partition edges into intra-file and cross-file relative to each source file.
    out_edges: dict[str, list] = defaultdict(list)  # source_file -> cross-file edges
    infile_edges: dict[str, list] = defaultdict(list)
    for e in links:
        src, tgt = e.get("source"), e.get("target")
        sf, tf = file_of.get(src), file_of.get(tgt)
        if sf is None or tf is None:
            continue
        if sf == tf:
            infile_edges[sf].append(e)
        else:
            out_edges[sf].append(e)

    out_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for source_file, fnodes in sorted(nodes_by_file.items()):
        file_types = {n.get("file_type") for n in fnodes}
        ctype = derive_type(source_file, file_types)
        communities = sorted({str(n.get("community")) for n in fnodes if n.get("community") is not None})
        tags = [f"community-{c}" for c in communities] + sorted(ft for ft in file_types if ft)
        rel = concept_relpath(source_file)
        title = Path(source_file).name

        body_parts = []
        body_parts.append("# Symbols\n")
        body_parts.append("| Symbol | Location | Kind |")
        body_parts.append("|--------|----------|------|")
        for n in sorted(fnodes, key=lambda x: (x.get("source_location", ""), x.get("label", ""))):
            label = n.get("norm_label") or n.get("label") or n["id"]
            loc = n.get("source_location", "")
            kind = n.get("file_type", "")
            body_parts.append(f"| `{label}` | {loc} | {kind} |")

        xedges = out_edges.get(source_file, [])
        if xedges:
            body_parts.append("\n# Relationships\n")
            body_parts.append(
                "_Directed edges to concepts in other files. "
                "`candidate` marks INFERRED edges — name-matched, ~0.8 confidence; "
                "verify at the cited location before relying on them for a risky change._\n"
            )
            for e in sorted(xedges, key=lambda x: (x.get("relation", ""), x.get("target", ""))):
                s_label = (node_by_id.get(e["source"], {}).get("norm_label")
                           or node_by_id.get(e["source"], {}).get("label") or e["source"])
                t_node = node_by_id.get(e["target"], {})
                t_label = t_node.get("norm_label") or t_node.get("label") or e["target"]
                t_path = "/" + concept_relpath(file_of[e["target"]])
                rel_name = e.get("relation", "links-to")
                conf = e.get("confidence", "")
                flag = " — `candidate`" if conf == "INFERRED" else ""
                loc = e.get("source_location", "")
                body_parts.append(
                    f"- `{s_label}` **{rel_name}** [`{t_label}`]({t_path}) ({loc}){flag}"
                )

        in_calls = [e for e in infile_edges.get(source_file, [])
                    if e.get("relation") in ("calls", "method")]
        if in_calls:
            body_parts.append("\n# In-file calls\n")
            body_parts.append(f"{len(in_calls)} intra-file call/method edge(s):\n")
            for e in sorted(in_calls, key=lambda x: x.get("source_location", "")):
                s_label = (node_by_id.get(e["source"], {}).get("norm_label")
                           or node_by_id.get(e["source"], {}).get("label") or e["source"])
                t_label = (node_by_id.get(e["target"], {}).get("norm_label")
                           or node_by_id.get(e["target"], {}).get("label") or e["target"])
                body_parts.append(f"- `{s_label}` {e.get('relation')} `{t_label}` ({e.get('source_location','')})")

        body_parts.append("\n# Citations\n")
        body_parts.append(f"[1] Source file `{source_file}` in repository `{name}`.")

        meta = {
            "type": ctype,
            "title": title,
            "description": f"Code-graph knowledge extracted from `{source_file}` "
                           f"({len(fnodes)} symbol(s), {len(xedges)} cross-file edge(s)).",
            "resource": source_file.replace("\\", "/"),
            "tags": tags,
            "timestamp": ts,
            "okf_source": "phoenix-code-graph",
        }
        if built_at:
            meta["built_at_commit"] = built_at

        write_concept(out_dir / rel, meta, "\n".join(body_parts))
        created.append(rel)

    _write_indexes(out_dir, created, name, ts)
    _write_log(out_dir, name, len(created), len(nodes), len(links), ts)
    return {"concepts": len(created), "nodes": len(nodes), "links": len(links)}


def _descr_of(out_dir: Path, rel: str) -> str:
    from okf_common import read_concept
    meta, _ = read_concept(out_dir / rel)
    if meta and meta.get("description"):
        return str(meta["description"])
    return ""


def _write_indexes(out_dir: Path, created: list[str], name: str, ts: str) -> None:
    # Collect every directory that needs an index, mapping dir -> (subdirs, concept files).
    dirs: dict[str, set] = defaultdict(set)
    files_in: dict[str, list] = defaultdict(list)
    for rel in created:
        parts = rel.split("/")
        for i in range(len(parts) - 1):
            parent = "/".join(parts[:i]) if i > 0 else ""
            child = parts[i]
            dirs[parent].add(child)
        parent = "/".join(parts[:-1])
        files_in[parent].append(rel)
    all_dirs = set(dirs) | set(files_in)

    for d in sorted(all_dirs):
        lines = []
        is_root = d == ""
        if is_root:
            # Root index.md is the ONLY place frontmatter is permitted in an index file.
            lines.append(dump_frontmatter({"okf_version": "0.1", "title": f"{name} code-graph bundle"}))
            lines.append("")
            lines.append(f"# {name} — code-graph knowledge bundle\n")
            lines.append(
                "OKF v0.1 bundle generated from the Phoenix code graph (`graph.json`) by "
                "`phoenix-okf`. Each concept mirrors one source file; cross-file edges are "
                "markdown links. Navigate one level at a time below.\n"
            )
        else:
            lines.append(f"# {d}/\n")

        subdirs = sorted(dirs.get(d, set()))
        if subdirs:
            lines.append("# Subdirectories\n")
            for sd in subdirs:
                child_path = f"{d}/{sd}" if d else sd
                lines.append(f"* [{sd}/]({sd}/) - concepts under `{child_path}/`")
            lines.append("")

        concept_files = sorted(files_in.get(d, []))
        if concept_files:
            lines.append("# Concepts\n")
            for rel in concept_files:
                fname = rel.split("/")[-1]
                desc = _descr_of(out_dir, rel)
                lines.append(f"* [{fname[:-3]}]({fname}) - {desc}")
            lines.append("")

        idx_path = out_dir / (d + "/index.md" if d else "index.md")
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_log(out_dir: Path, name: str, concepts: int, nodes: int, links: int, ts: str) -> None:
    date = ts[:10]
    text = (
        "# Directory Update Log\n\n"
        f"## {date}\n"
        f"* **Initialization**: Generated OKF v0.1 bundle for `{name}` from the Phoenix code "
        f"graph — {concepts} concept document(s) covering {nodes} graph node(s) and {links} "
        f"edge(s). See the root [index](/index.md).\n"
    )
    (out_dir / "log.md").write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Export a graphify graph.json to an OKF v0.1 bundle.")
    ap.add_argument("--graph", default=".token-master/graph.json", type=Path)
    ap.add_argument("--out", default="okf-out", type=Path)
    ap.add_argument("--name", default=None, help="Repository / bundle name (default: cwd name).")
    args = ap.parse_args()

    name = args.name or Path.cwd().name
    stats = build(args.graph, args.out, name)
    print(f"OKF bundle written to {args.out}/")
    print(f"  concepts: {stats['concepts']}  (from {stats['nodes']} nodes, {stats['links']} edges)")


if __name__ == "__main__":
    main()
