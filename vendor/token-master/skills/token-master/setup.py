#!/usr/bin/env python
"""TokenMaster installer.

Turns on token-efficient graph routing for a repository, targeting either Claude Code
or GitHub Copilot CLI (the "host"):

  1. Verifies `graphify` is installed.
  2. Builds the code graph (`graphify update`) and relocates it to
     ``<repo>/.token-master/graph.json``.
  3. Adds ``.token-master/`` and ``.codegraph/`` to the repo's ``.gitignore``.
  4. Copies the graph MCP server to a stable home
     (``<host-home>/token-master/graphify_mcp.py``).
  5. Locates or installs the codegraph shim (optional, best-effort).
  6. Indexes the repo with codegraph if the shim is available.
  7. Checks for sparse call-graph coverage and warns if detected.
  8. Writes the routing agent in the host's format:
       - Copilot: ``~/.copilot/agents/token-master.agent.md`` (MCP servers declared
         inline in the agent frontmatter).
       - Claude:  ``~/.claude/agents/token-master.md`` (Claude frontmatter, no inline
         MCP) plus the graph MCP server merged into ``~/.claude.json`` ``mcpServers``.
     Paths are resolved absolute (``uv``/script) with a relative graph path, so the one
     agent serves every repo.

The host is chosen by: ``--host=claude|copilot`` arg > ``TOKEN_MASTER_HOST`` env >
autodetect > default ``claude``.

Idempotent: safe to re-run to refresh the index or repair the install.

Usage: python setup.py [REPO_ROOT] [--host=claude|copilot]
       (REPO_ROOT defaults to the current dir)
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
GITIGNORE_LINE = ".token-master/"
GITIGNORE_CG_LINE = ".codegraph/"


def _resolve_host(argv_host: str = "") -> str:
    """Pick the target host CLI: 'claude' or 'copilot'.

    Priority: explicit --host arg > TOKEN_MASTER_HOST env > autodetect > default 'claude'.
    Autodetect prefers Copilot only when its signals are present and Claude's are not, so a
    machine with both falls through to the 'claude' default.
    """
    explicit = (argv_host or os.environ.get("TOKEN_MASTER_HOST", "")).strip().lower()
    if explicit in ("claude", "copilot"):
        return explicit

    claude_signal = bool(os.environ.get("CLAUDE_PLUGIN_ROOT")) or (Path.home() / ".claude").is_dir()
    copilot_signal = bool(os.environ.get("COPILOT_HOME")) or (Path.home() / ".copilot").is_dir()
    if copilot_signal and not claude_signal:
        return "copilot"
    return "claude"


def _host_home(host: str) -> Path:
    """User-scope home for the target host CLI, honoring the host's env override."""
    if host == "copilot":
        raw = os.environ.get("COPILOT_HOME")
        default = Path.home() / ".copilot"
    else:
        raw = os.environ.get("CLAUDE_HOME")
        default = Path.home() / ".claude"
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    return default.resolve()


def _claude_mcp_config_path() -> Path:
    """User-scope file where Claude Code stores its `mcpServers` map (`~/.claude.json`)."""
    return (Path.home() / ".claude.json").resolve()


def _git_root(start: Path) -> Path:
    """Return the git toplevel for `start`, or `start` if not in a git repo."""
    git = shutil.which("git")
    if not git:
        return start
    try:
        out = subprocess.run(
            [git, "rev-parse", "--show-toplevel"],
            cwd=str(start),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        root = out.stdout.strip()
        return Path(root).resolve() if root else start
    except (subprocess.CalledProcessError, OSError):
        return start


def _fail(msg: str) -> int:
    print(f"[token-master] ERROR: {msg}")
    return 1


def _ensure_gitignore_lines(gitignore: Path, lines: list) -> None:
    """Add any missing lines to .gitignore (best effort, idempotent)."""
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
        existing_lines = existing.splitlines()
        to_add = [ln for ln in lines if ln not in existing_lines]
        if not to_add:
            return
        with open(gitignore, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            for ln in to_add:
                fh.write(f"{ln}\n")
    except OSError as exc:
        print(f"[token-master] warning: could not update .gitignore ({exc})")


def _ensure_codegraph(home: Path):
    """Locate or install the codegraph shim.

    Returns (node_path, shim_path) if codegraph is available, or (None, None)
    if node is missing or installation failed.  All failures are non-fatal.
    """
    node = shutil.which("node")
    if not node:
        print("[token-master] codegraph: `node` not found on PATH — skipping codegraph backend.")
        return None, None

    # 1. Explicit env override.
    env_shim = os.environ.get("TOKEN_MASTER_CG_SHIM", "")
    if env_shim:
        p = Path(env_shim)
        if p.is_file():
            return node, str(p)
        print(
            f"[token-master] warning: TOKEN_MASTER_CG_SHIM={env_shim!r} does not exist, "
            "falling back to local install."
        )

    # 2. Stable local install home.
    cg_home = home / "token-master" / "cgtool"
    shim_path = (
        cg_home / "node_modules" / "@colbymchenry" / "codegraph" / "npm-shim.js"
    )
    if shim_path.is_file():
        return node, str(shim_path)

    # 3. Attempt local npm install.
    npm = shutil.which("npm")
    if not npm:
        print("[token-master] codegraph: `npm` not found — skipping codegraph backend.")
        return None, None

    print(f"[token-master] codegraph: installing @colbymchenry/codegraph into {cg_home} ...")
    try:
        cg_home.mkdir(parents=True, exist_ok=True)
        pkg_json = cg_home / "package.json"
        if not pkg_json.is_file():
            subprocess.run(
                [npm, "init", "-y"],
                cwd=str(cg_home),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        subprocess.run(
            [npm, "install", "@colbymchenry/codegraph"],
            cwd=str(cg_home),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        msg = getattr(exc, "output", None) or str(exc)
        print(
            f"[token-master] codegraph: npm install failed ({msg!r}) — "
            "skipping codegraph backend."
        )
        return None, None

    if shim_path.is_file():
        print("[token-master] codegraph: installed successfully.")
        return node, str(shim_path)

    print(
        "[token-master] codegraph: shim not found after install — skipping codegraph backend."
    )
    return None, None


def _codegraph_node_count(node_path: str, shim_path: str, repo: Path):
    """Return codegraph's indexed node count via ``status --json``, or None on failure.

    Used as a post-index sanity check: a codegraph DB that built but holds zero nodes
    cannot answer structural queries, so we should not advertise it as a backend.
    """
    try:
        out = subprocess.run(
            [node_path, shim_path, "status", "--json", "."],
            cwd=str(repo),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        data = json.loads(out.stdout)
        return int(data.get("nodeCount", 0))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError, TypeError):
        return None


def _calls_edge_count(graph_path: Path):
    """Return the count of 'calls' edges in a networkx node-link graph JSON.

    The graph uses the node-link serialisation: links are under ``"links"``, each
    link dict carries the relation in a ``"relation"`` or ``"type"`` key.
    Returns None if the file cannot be read or parsed.
    """
    try:
        with open(graph_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        links = data.get("links", [])
        return sum(
            1 for lnk in links
            if (lnk.get("relation") or lnk.get("type")) == "calls"
        )
    except (OSError, ValueError):
        return None


def _strip_codegraph_from_template(template: str) -> str:
    """Remove the codegraph mcp-server block and tool reference from the agent template.

    Handles both host formats:
      - Copilot: a quoted ``'codegraph/*'`` entry in the tools list plus an inline
        ``  codegraph:`` mcp-server block.
      - Claude: a bare ``codegraph`` token in a comma-separated tools string and no
        inline mcp-server block (the codegraph block detection is simply a no-op there).

    Operates line-by-line so it is robust to any surrounding whitespace changes.
    """
    lines = template.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\r\n")

        # Remove the codegraph entry from the top-level tools list (either format).
        if stripped.lstrip().startswith("tools:") and "codegraph" in stripped:
            new_stripped = (
                stripped
                # Copilot quoted-glob form.
                .replace("'codegraph/*', ", "")
                .replace(", 'codegraph/*'", "")
                .replace("'codegraph/*'", "")
                # Claude bare-token comma-string form.
                .replace("codegraph, ", "")
                .replace(", codegraph", "")
                .replace("codegraph", "")
            )
            eol = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            out.append(new_stripped + eol)
            i += 1
            continue

        # Detect start of the codegraph mcp-server block (exactly "  codegraph:").
        if stripped == "  codegraph:":
            # Consume this line and all subsequent more-deeply-indented lines.
            i += 1
            while i < len(lines):
                next_stripped = lines[i].rstrip("\r\n")
                # A non-empty line with fewer than 3 leading spaces is a sibling
                # server entry or end of the mcp-servers block — stop consuming.
                if next_stripped and not next_stripped.startswith("   "):
                    break
                i += 1
            continue

        out.append(line)
        i += 1
    return "".join(out)


def _write_claude_mcp_servers(uv: str, mcp_script: str, node_path, shim_path) -> Path:
    """Merge TokenMaster's graph MCP server(s) into Claude Code's ``~/.claude.json``.

    Claude Code reads user-scope MCP servers from the top-level ``mcpServers`` map in
    ``~/.claude.json`` (not the agent frontmatter). This is a read-modify-write that
    overwrites only the ``graphify-nav`` / ``codegraph`` keys, so it is idempotent and
    leaves the user's other servers untouched. Returns the config path written.
    """
    cfg_path = _claude_mcp_config_path()
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}

    servers["graphify-nav"] = {
        "command": uv,
        "args": ["run", "--with", "mcp", "python", mcp_script],
        "env": {"GRAPH_PATH": ".token-master/graph.json"},
    }
    if node_path and shim_path:
        servers["codegraph"] = {
            "command": node_path,
            "args": [shim_path, "serve", "--mcp", "-p", "."],
        }
    else:
        # Remove a stale codegraph entry from a prior install so we don't point Claude
        # at a server that is no longer available.
        servers.pop("codegraph", None)

    data["mcpServers"] = servers
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def main() -> int:
    # Parse args: an optional REPO_ROOT positional plus an optional --host=claude|copilot.
    argv_host = ""
    positionals = []
    for arg in sys.argv[1:]:
        if arg.startswith("--host="):
            argv_host = arg.split("=", 1)[1]
        elif arg in ("--host", "-H"):
            continue  # value-less form ignored; require --host=VALUE
        else:
            positionals.append(arg)

    host = _resolve_host(argv_host)
    passed = Path(positionals[0]).resolve() if positionals else Path.cwd()
    if not passed.is_dir():
        return _fail(f"repository path is not a directory: {passed}")
    repo = _git_root(passed)
    if repo != passed:
        print(f"[token-master] using git root: {repo}")
    print(f"[token-master] host: {host}")

    graphify = shutil.which("graphify")
    if not graphify:
        return _fail(
            "`graphify` not found on PATH. Install it with `uv tool install graphify` "
            "(https://github.com/safishamsi/graphify), then run /token-master again."
        )
    if not shutil.which("uv"):
        return _fail(
            "`uv` not found on PATH, but the routing agent runs the graph server via `uv`. "
            "Install uv (https://docs.astral.sh/uv/) and run /token-master again."
        )

    print(f"[token-master] indexing {repo} ...")
    try:
        subprocess.run(
            [graphify, "update", "."],
            cwd=str(repo),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        return _fail(f"`graphify update` failed:\n{exc.output}")

    src_graph = repo / "graphify-out" / "graph.json"
    if not src_graph.is_file():
        return _fail(f"expected graph not produced at {src_graph}")

    code_nodes = _code_node_count(src_graph)
    if not code_nodes:
        return _fail(
            "graphify indexed no code symbols — this repo may have no supported source files. "
            "Nothing to route; not enabling TokenMaster."
        )

    # Relocate the graph into the canonical .token-master/ home.
    tm_dir = repo / ".token-master"
    tm_dir.mkdir(exist_ok=True)
    shutil.copy2(src_graph, tm_dir / "graph.json")
    # Clean up graphify's scratch output so it doesn't litter the working tree.
    shutil.rmtree(repo / "graphify-out", ignore_errors=True)

    # Gitignore the per-repo build artifacts (best effort).
    _ensure_gitignore_lines(repo / ".gitignore", [GITIGNORE_LINE, GITIGNORE_CG_LINE])

    # Install the MCP server to a stable, install-independent location.
    home = _host_home(host)
    install_dir = home / "token-master"
    install_dir.mkdir(parents=True, exist_ok=True)
    mcp_target = install_dir / "graphify_mcp.py"
    shutil.copy2(SKILL_DIR / "graphify_mcp.py", mcp_target)

    # Locate or install codegraph (best effort, optional).
    node_path, shim_path = _ensure_codegraph(home)

    # Index with codegraph if the shim is available.
    if node_path and shim_path:
        # codegraph requires `init` (which builds the initial index and creates
        # .codegraph/codegraph.db) before `index`/`sync` will run — calling `index`
        # on an uninitialized repo errors with "CodeGraph not initialized". So pick
        # the subcommand by whether the repo has been initialized already.
        cg_db = repo / ".codegraph" / "codegraph.db"
        if cg_db.is_file():
            cg_cmd, cg_action = [node_path, shim_path, "sync", "."], "syncing"
        else:
            cg_cmd, cg_action = [node_path, shim_path, "init", "."], "initializing"
        print(f"[token-master] codegraph: {cg_action} {repo} ...")
        try:
            subprocess.run(
                cg_cmd,
                cwd=str(repo),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            print("[token-master] codegraph: index complete.")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            msg = getattr(exc, "output", None) or str(exc)
            print(
                f"[token-master] warning: codegraph indexing failed ({msg!r}) — "
                "continuing graphify-only."
            )
            node_path, shim_path = None, None

    # Post-index sanity check: a codegraph DB that built but indexed zero nodes
    # cannot answer structural queries, so don't advertise it as a backend.
    if node_path and shim_path:
        cg_nodes = _codegraph_node_count(node_path, shim_path, repo)
        if cg_nodes is None:
            print(
                "[token-master] warning: could not read codegraph status — "
                "continuing graphify-only."
            )
            node_path, shim_path = None, None
        elif cg_nodes == 0:
            print(
                "[token-master] warning: codegraph indexed 0 nodes for this repo — "
                "continuing graphify-only."
            )
            node_path, shim_path = None, None
        else:
            print(f"[token-master] codegraph: {cg_nodes} nodes indexed.")

    # Sparse call-graph gate.
    graph_json = tm_dir / "graph.json"
    calls_edge_count = _calls_edge_count(graph_json)
    sparse_warning = False
    if calls_edge_count is not None and code_nodes:
        # Ratio-based: a healthy call graph has roughly one 'calls' edge per code
        # symbol; below ~0.1 edges/symbol the call graph is effectively absent and
        # "who calls X" will fall back to grep. (Django ~0.73 dense; Express ~0.06
        # sparse — a 12x gap an absolute floor fails to separate.)
        threshold = code_nodes * 0.1
        if calls_edge_count < threshold:
            sparse_warning = True
            cg_note = (
                "codegraph (installed) will be the better backend for call-resolution here."
                if node_path
                else "Installing codegraph (`node` + `npm` required) would provide "
                "AST-resolved call edges for this repo."
            )
            print(
                f"[token-master] WARNING: sparse call graph detected — "
                f"{calls_edge_count} 'calls' edges for {code_nodes} code symbols "
                f"(threshold {threshold:.0f}). "
                "This is common in JavaScript/TypeScript repos (e.g. Express had 19 calls edges "
                f"for 313 code nodes). 'Who calls X' queries may fall back to grep. {cg_note}"
            )

    # Write the routing agent (user scope), resolving paths for this machine.
    # The agent template and its install location/format are host-specific; the MCP
    # server, its launch command, and the path substitutions are shared.
    uv = shutil.which("uv") or "uv"
    if host == "copilot":
        template_name = "agent.template.copilot.md"
        agent_filename = "token-master.agent.md"
    else:
        template_name = "agent.template.claude.md"
        agent_filename = "token-master.md"
    template = (SKILL_DIR / template_name).read_text(encoding="utf-8")

    if node_path and shim_path:
        agent = (
            template
            .replace("__UV__", uv.replace("\\", "/"))
            .replace("__MCP_SCRIPT__", str(mcp_target).replace("\\", "/"))
            .replace("__NODE__", node_path.replace("\\", "/"))
            .replace("__CG_SHIM__", shim_path.replace("\\", "/"))
        )
    else:
        # Strip the codegraph references so the host doesn't try to launch a broken server.
        if not shutil.which("node"):
            skip_reason = "node not found"
        else:
            skip_reason = "npm install failed or shim missing"
        print(
            f"[token-master] codegraph: skipped ({skip_reason}) — writing graphify-only agent."
        )
        stripped = _strip_codegraph_from_template(template)
        agent = (
            stripped
            .replace("__UV__", uv.replace("\\", "/"))
            .replace("__MCP_SCRIPT__", str(mcp_target).replace("\\", "/"))
        )

    agents_dir = home / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_path = agents_dir / agent_filename
    agent_path.write_text(agent, encoding="utf-8")

    # Claude Code wires MCP servers via ~/.claude.json, not the agent frontmatter, so
    # register the graph server(s) there. (Copilot's servers live inline in the agent.)
    mcp_config_path = None
    if host == "claude":
        mcp_config_path = _write_claude_mcp_servers(
            uv.replace("\\", "/"),
            str(mcp_target).replace("\\", "/"),
            node_path.replace("\\", "/") if node_path else None,
            shim_path.replace("\\", "/") if shim_path else None,
        )

    node_count = _node_count(graph_json)

    # Build summary lines.
    summary = ["[token-master] done."]
    graph_line = f"  graph:  {graph_json}"
    if node_count is not None:
        graph_line += f"  ({node_count} nodes)"
    summary.append(graph_line)
    if calls_edge_count is not None:
        ce_line = f"  calls edges: {calls_edge_count}"
        if sparse_warning:
            ce_line += " (SPARSE — see warning above)"
        summary.append(ce_line)
    summary.append(f"  agent:  {agent_path}")
    summary.append(f"  server: {mcp_target}")
    if mcp_config_path is not None:
        summary.append(f"  mcp config: {mcp_config_path}")
    if node_path and shim_path:
        summary.append(f"  codegraph: {shim_path}")
    else:
        if not shutil.which("node"):
            summary.append("  codegraph: skipped (node not found)")
        else:
            summary.append("  codegraph: skipped (npm install failed or shim missing)")
    if host == "copilot":
        summary.append(
            "Restart Copilot (or start it with `copilot --agent token-master`) to activate "
            "routing, then ask structural questions normally."
        )
    else:
        summary.append(
            "Restart Claude Code (or start it with `claude --agent token-master`) to activate "
            "routing, then ask structural questions normally."
        )
    print("\n".join(summary))
    return 0


def _node_count(graph_path: Path):
    try:
        with open(graph_path, "r", encoding="utf-8") as fh:
            return len(json.load(fh).get("nodes", []))
    except (OSError, ValueError):
        return None


def _code_node_count(graph_path: Path):
    try:
        with open(graph_path, "r", encoding="utf-8") as fh:
            nodes = json.load(fh).get("nodes", [])
        return sum(1 for n in nodes if n.get("file_type") == "code")
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
