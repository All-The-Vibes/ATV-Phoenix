#!/usr/bin/env python
"""TokenMaster graph-navigation MCP server.

Exposes a prebuilt code graph behind routing-friendly tool names so the host CLI
will call them for structural ("who calls X", "what breaks if I change Y") questions
instead of repeatedly grepping and re-reading files. That substitution is what
cuts cumulative context tokens.

Design notes:
  * Lazy-loads the graph on the first tool call, so the server registers cleanly
    even before an index exists.
  * GRAPH_PATH defaults to repo-relative ``.token-master/graph.json``. The MCP
    server inherits the workspace root as its working directory, so this single
    relative default works across every repository.
  * Honesty: ``calls`` edges are name-based INFERRED candidates (confidence
    ~0.8), not a verified call graph. Every response says so; the graph is a
    CANDIDATE GENERATOR and callers must verify each hit at the cited
    file:line.

Run: uv run --with mcp python graphify_mcp.py
"""
import collections
import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# GRAPH_PATH may be absolute or relative. When relative (the default), the graph
# is located by walking UP from the current working directory looking for that
# path — so it resolves whether the host CLI launches the MCP server at the repo
# root or in a subdirectory.
GRAPH_PATH = os.environ.get("GRAPH_PATH", os.path.join(".token-master", "graph.json"))
# Optional: set MCP_CALL_LOG to record each tool call (used by the observability
# meter). Off by default so the server never litters the repo.
CALL_LOG = os.environ.get("MCP_CALL_LOG")

# Caps to preserve the whole point of this server — token efficiency — on large
# repos, where a symbol like `run`/`main` can resolve or fan out enormously.
MAX_DEFS = 8     # if a name resolves to more definitions, force disambiguation
MAX_ROWS = 60    # max rows a single tool will emit before truncating

_STATE = {"loaded": False, "NODES": {}, "OUT": None, "IN": None, "BY_NAME": None}


def _find_graph() -> str:
    """Resolve the graph file. Absolute GRAPH_PATH is used as-is; a relative one
    is searched for from cwd upward to the filesystem root."""
    p = Path(GRAPH_PATH)
    if p.is_absolute():
        return str(p)
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        cand = d / p
        if cand.is_file():
            return str(cand)
    return str(here / p)  # not found; reported as a clear error on load


def _norm(label: str) -> str:
    return str(label).strip().rstrip("()").lower()


def _log(tool: str, symbol: str) -> None:
    if not CALL_LOG:
        return
    try:
        os.makedirs(os.path.dirname(CALL_LOG) or ".", exist_ok=True)
        with open(CALL_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{tool}\t{symbol}\n")
    except OSError:
        pass


def _ensure_loaded():
    """Load the graph on first use. Returns an error message string on failure,
    or None on success — so tools degrade to a clear diagnostic instead of
    crashing."""
    if _STATE["loaded"]:
        return None
    path = _find_graph()
    if not os.path.isfile(path):
        return (
            f"TokenMaster graph not found (looked for '{GRAPH_PATH}' from "
            f"{Path.cwd()} upward). Run /token-master in this repo to build it."
        )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            graph = json.load(fh)
        node_list = graph["nodes"]
        link_list = graph["links"]
    except (ValueError, KeyError, OSError) as exc:
        return (
            f"TokenMaster graph at '{path}' is missing or invalid ({exc}). "
            "Re-run /token-master to rebuild it."
        )
    if not node_list:
        return (
            f"TokenMaster graph at '{path}' has no nodes — the repo may be "
            "unsupported or empty. Re-run /token-master after adding source files."
        )
    nodes = {n["id"]: n for n in node_list}
    by_name = collections.defaultdict(list)
    for n in node_list:
        if n.get("file_type") == "code":
            by_name[_norm(n.get("label", ""))].append(n["id"])
    out = collections.defaultdict(list)
    inn = collections.defaultdict(list)
    for link in link_list:
        out[link["source"]].append((link["relation"], link["target"], link))
        inn[link["target"]].append((link["relation"], link["source"], link))
    _STATE.update(loaded=True, NODES=nodes, OUT=out, IN=inn, BY_NAME=by_name)
    return None


def _ambiguity_msg(symbol: str, ids) -> str:
    rows = [f"  - id={i}  {_STATE['NODES'][i].get('label')}  [{_loc(_STATE['NODES'][i])}]" for i in ids[:MAX_DEFS]]
    extra = "" if len(ids) <= MAX_DEFS else f"\n  ... (+{len(ids) - MAX_DEFS} more)"
    return (
        f"'{symbol}' is ambiguous — {len(ids)} definitions. Re-run with a specific "
        f"id (the tools accept a node id as the symbol):\n" + "\n".join(rows) + extra
    )


def _resolve(symbol: str):
    if symbol in _STATE["NODES"]:
        return [symbol]
    return list(_STATE["BY_NAME"].get(_norm(symbol), []))


def _loc(node) -> str:
    return f"{node.get('source_file', '?')}:{node.get('source_location', '?')}"


mcp = FastMCP("graphify-nav")


@mcp.tool()
def find(symbol: str) -> str:
    """Resolve a symbol name to its definition(s) in the code graph.

    Returns each matching node with its file:line so you can disambiguate before
    asking for callers/callees/impact."""
    err = _ensure_loaded()
    if err:
        return err
    _log("find", symbol)
    ids = _resolve(symbol)
    if not ids:
        return f"No definition node found for '{symbol}'."
    out = [f"Definitions of '{symbol}' ({len(ids)}):"]
    for i in ids[:MAX_ROWS]:
        n = _STATE["NODES"][i]
        out.append(f"  - {n.get('label')}  [{_loc(n)}]  id={i}  type={n.get('file_type')}")
    if len(ids) > MAX_ROWS:
        out.append(f"  ... (+{len(ids) - MAX_ROWS} more)")
    return "\n".join(out)


@mcp.tool()
def callers(symbol: str) -> str:
    """List DIRECT callers of a function/method (one hop, reverse `calls`).

    Each row is name + source file:line + edge confidence. Edges are INFERRED
    (name-based) — verify each at the cited file:line before trusting it."""
    err = _ensure_loaded()
    if err:
        return err
    _log("callers", symbol)
    ids = _resolve(symbol)
    if not ids:
        return f"No definition node found for '{symbol}'."
    if len(ids) > MAX_DEFS:
        return _ambiguity_msg(symbol, ids)
    rows, seen = [], set()
    for tid in ids:
        for rel, sid, link in _STATE["IN"].get(tid, []):
            if rel != "calls":
                continue
            s = _STATE["NODES"].get(sid, {})
            key = (s.get("label"), s.get("source_file"), link.get("source_location"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                f"  - {s.get('label')}  [{s.get('source_file')}:{link.get('source_location')}]"
                f"  conf={link.get('confidence')}"
            )
    if not rows:
        return f"No callers of '{symbol}' in graph (note: graph may miss dynamic dispatch)."
    total = len(rows)
    capped = rows[:MAX_ROWS]
    head = f"DIRECT callers of '{symbol}' ({total}) — INFERRED edges, verify at source:"
    if total > MAX_ROWS:
        capped.append(f"  ... (+{total - MAX_ROWS} more; refine by id)")
    return head + "\n" + "\n".join(capped)


@mcp.tool()
def callees(symbol: str) -> str:
    """List what a function/method DIRECTLY calls (one hop, forward `calls`)."""
    err = _ensure_loaded()
    if err:
        return err
    _log("callees", symbol)
    ids = _resolve(symbol)
    if not ids:
        return f"No definition node found for '{symbol}'."
    if len(ids) > MAX_DEFS:
        return _ambiguity_msg(symbol, ids)
    rows, seen = [], set()
    for sid in ids:
        for rel, tid, link in _STATE["OUT"].get(sid, []):
            if rel != "calls":
                continue
            t = _STATE["NODES"].get(tid, {})
            key = (t.get("label"), link.get("source_location"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                f"  - {t.get('label')}  [defined {_loc(t)}]  call@{link.get('source_location')}"
                f"  conf={link.get('confidence')}"
            )
    if not rows:
        return f"'{symbol}' has no outgoing call edges in graph."
    total = len(rows)
    capped = rows[:MAX_ROWS]
    if total > MAX_ROWS:
        capped.append(f"  ... (+{total - MAX_ROWS} more)")
    return f"DIRECT callees of '{symbol}' ({total}):\n" + "\n".join(capped)


@mcp.tool()
def impact(symbol: str, depth: int = 3) -> str:
    """Transitive blast radius: every function/method that can reach `symbol`
    through up to `depth` reverse `calls` hops. Use to find everything affected
    if `symbol`'s behavior/signature changes. INFERRED edges compound over hops,
    so deeper results are less reliable — verify the chain at source."""
    err = _ensure_loaded()
    if err:
        return err
    _log("impact", symbol)
    ids = _resolve(symbol)
    if not ids:
        return f"No definition node found for '{symbol}'."
    if len(ids) > MAX_DEFS:
        return _ambiguity_msg(symbol, ids)
    try:
        depth = max(1, min(int(depth), 5))
    except (TypeError, ValueError):
        depth = 3
    frontier = set(ids)
    visited = set(ids)
    levels = []
    for _hop in range(depth):
        nxt = set()
        for tid in frontier:
            for rel, sid, _link in _STATE["IN"].get(tid, []):
                if rel == "calls" and sid not in visited:
                    nxt.add(sid)
        if not nxt:
            break
        visited |= nxt
        levels.append(nxt)
        frontier = nxt
    total = sum(len(lvl) for lvl in levels)
    out = [
        f"IMPACT of '{symbol}' ({total}) transitive callers within {len(levels)} hop(s) "
        f"(INFERRED edges, deeper = less reliable):"
    ]
    for i, lvl in enumerate(levels, 1):
        out.append(f" hop {i} ({len(lvl)}):")
        for nid in sorted(lvl):
            n = _STATE["NODES"].get(nid, {})
            out.append(f"    - {n.get('label')}  [{_loc(n)}]")
            if len(out) > 120:
                out.append(f"    ... (truncated; {total} total)")
                return "\n".join(out)
    return "\n".join(out)


@mcp.tool()
def inheritors(symbol: str) -> str:
    """List classes that inherit from `symbol` (reverse `inherits` edges) and,
    for each, the methods it defines (so you can see overrides)."""
    err = _ensure_loaded()
    if err:
        return err
    _log("inheritors", symbol)
    ids = _resolve(symbol)
    if not ids:
        return f"No class node found for '{symbol}'."
    if len(ids) > MAX_DEFS:
        return _ambiguity_msg(symbol, ids)
    rows = []
    for tid in ids:
        for rel, sid, _link in _STATE["IN"].get(tid, []):
            if rel != "inherits":
                continue
            c = _STATE["NODES"].get(sid, {})
            methods = [
                _STATE["NODES"].get(mt, {}).get("label")
                for r2, mt, _l in _STATE["OUT"].get(sid, [])
                if r2 == "method"
            ]
            mlist = ", ".join(m for m in methods if m) or "(no methods in graph)"
            rows.append(f"  - {c.get('label')}  [{_loc(c)}]\n      methods: {mlist}")
    if not rows:
        return f"No subclasses of '{symbol}' in graph."
    total = len(rows)
    capped = rows[:MAX_ROWS]
    if total > MAX_ROWS:
        capped.append(f"  ... (+{total - MAX_ROWS} more)")
    return f"Subclasses of '{symbol}' ({total}):\n" + "\n".join(capped)


@mcp.tool()
def explain(symbol: str) -> str:
    """Show a symbol's node plus all its immediate neighbors across every relation
    (contains/method/calls/inherits/uses/imports). Good for orienting before a
    deeper query."""
    err = _ensure_loaded()
    if err:
        return err
    _log("explain", symbol)
    ids = _resolve(symbol)
    if not ids:
        return f"No node found for '{symbol}'."
    out = []
    for nid in ids[:MAX_DEFS]:
        n = _STATE["NODES"][nid]
        out.append(f"{n.get('label')}  [{_loc(n)}]  id={nid}")
        grouped = collections.defaultdict(list)
        for rel, tid, _link in _STATE["OUT"].get(nid, []):
            grouped["out:" + rel].append(_STATE["NODES"].get(tid, {}).get("label"))
        for rel, sid, _link in _STATE["IN"].get(nid, []):
            grouped["in:" + rel].append(_STATE["NODES"].get(sid, {}).get("label"))
        for k in sorted(grouped):
            vals = [v for v in grouped[k] if v][:12]
            extra = "" if len(grouped[k]) <= 12 else f" (+{len(grouped[k]) - 12} more)"
            out.append(f"   {k} ({len(grouped[k])}): {', '.join(vals)}{extra}")
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run()
