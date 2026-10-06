#!/usr/bin/env python
"""Brainspace installer — wires the compression layer into Claude Code or Copilot CLI.

This complements TokenMaster's setup.py (graph routing) with the compression layer.
It is intentionally a separate entry point so the compression feature is additive:
running it never disturbs the graph-routing install, and vice versa. It reuses the
exact host-resolution and home-resolution conventions of setup.py, including the
``CLAUDE_HOME`` / ``COPILOT_HOME`` env overrides — which is also what lets the test
suite install into a throwaway sandbox home instead of the user's real ~/.claude.

What it does, per host:

  Claude Code  (full layer — auto-compress + model-invoked tools):
    * Copies brainspace_mcp.py, brainspace_posttooluse.py, and the brainspace/ package to
      ``<CLAUDE_HOME>/token-master/``.
    * Registers the ``brainspace`` MCP server in ``~/.claude.json`` mcpServers
      (idempotent read-modify-write touching only the ``brainspace`` key).
    * Registers the PostToolUse hook in ``<CLAUDE_HOME>/settings.json`` so tool
      outputs are auto-compressed at the append boundary (verified field:
      hookSpecificOutput.updatedToolOutput).

  Copilot CLI  (MCP-only — model-invoked compress + retrieve):
    * Copies the same files to ``<COPILOT_HOME>/token-master/``.
    * Registers the ``brainspace`` MCP server in ``<COPILOT_HOME>/mcp-config.json``.
    * Does NOT install an auto-compress hook: Copilot CLI does not document a
      PostToolUse output-rewriting hook, so on Copilot the layer is honestly
      opt-in (the model calls brainspace_compress / brainspace_retrieve). This
      limitation is printed in the summary, not hidden.

Idempotent and reversible-by-key: re-running refreshes; uninstall removes only the
``brainspace`` keys it added.

Usage: python brainspace_setup.py [REPO_ROOT] [--host=claude|copilot] [--uninstall]
"""
import json
import os
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent

# Packages the server/hook need at launch beyond `mcp`. Without the tree-sitter
# grammars the code compressor silently degrades to a no-op (it lazy-imports them
# and returns content unchanged when absent), so code outputs would never be
# skeletonized in a real install; tiktoken gives the never-expand guard an exact
# token count instead of the chars/4 heuristic. These are declared here, in one
# place, so the MCP server (both hosts) and the PostToolUse hook stay in sync.
RUN_WITH = ("mcp", "tree-sitter", "tree-sitter-python", "tree-sitter-rust", "tiktoken")


def _uv_run_args(script: str) -> list:
    """`uv run --with <each dep> python <script>` as an argv list (for JSON
    mcpServers entries)."""
    args = ["run"]
    for dep in RUN_WITH:
        args += ["--with", dep]
    args += ["python", script]
    return args


def _uv_run_cmd(uv: str, script: str) -> str:
    """The same invocation as a shell command string (for the hook entry)."""
    withs = " ".join(f"--with {dep}" for dep in RUN_WITH)
    return f'{uv} run {withs} python "{script}"'


# -- host / home resolution (mirrors setup.py exactly) -------------------------

def _resolve_host(argv_host: str = "") -> str:
    explicit = (argv_host or os.environ.get("TOKEN_MASTER_HOST", "")).strip().lower()
    if explicit in ("claude", "copilot"):
        return explicit
    claude_signal = bool(os.environ.get("CLAUDE_PLUGIN_ROOT")) or (Path.home() / ".claude").is_dir()
    copilot_signal = bool(os.environ.get("COPILOT_HOME")) or (Path.home() / ".copilot").is_dir()
    if copilot_signal and not claude_signal:
        return "copilot"
    return "claude"


def _host_home(host: str) -> Path:
    if host == "copilot":
        raw = os.environ.get("COPILOT_HOME")
        default = Path.home() / ".copilot"
    else:
        raw = os.environ.get("CLAUDE_HOME")
        default = Path.home() / ".claude"
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    return default.resolve()


def _claude_json_path() -> Path:
    """``~/.claude.json`` — but honor CLAUDE_HOME so a sandbox can redirect it.

    Claude Code itself reads ~/.claude.json from the real home; for test isolation
    we allow CLAUDE_CONFIG to point elsewhere, falling back to <CLAUDE_HOME>/.claude.json
    when CLAUDE_HOME is set, else ~/.claude.json.
    """
    cfg = os.environ.get("CLAUDE_CONFIG")
    if cfg:
        return Path(os.path.expandvars(os.path.expanduser(cfg))).resolve()
    chome = os.environ.get("CLAUDE_HOME")
    if chome:
        return (Path(os.path.expandvars(os.path.expanduser(chome))).resolve() / ".claude.json")
    return (Path.home() / ".claude.json").resolve()


def _fail(msg: str) -> int:
    print(f"[brainspace] ERROR: {msg}")
    return 1


# -- file install --------------------------------------------------------------

def _install_files(home: Path) -> Path:
    """Copy the server, hook, benchmark, and brainspace/ package to <home>/token-master/."""
    install_dir = home / "token-master"
    install_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL_DIR / "brainspace_mcp.py", install_dir / "brainspace_mcp.py")
    shutil.copy2(SKILL_DIR / "brainspace_posttooluse.py", install_dir / "brainspace_posttooluse.py")
    shutil.copy2(SKILL_DIR / "brainspace_benchmark.py", install_dir / "brainspace_benchmark.py")
    # Copy the package (clean any stale copy first so removed files don't linger).
    pkg_dst = install_dir / "brainspace"
    if pkg_dst.exists():
        shutil.rmtree(pkg_dst, ignore_errors=True)
    shutil.copytree(
        SKILL_DIR / "brainspace",
        pkg_dst,
        ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc"),
    )
    return install_dir


# -- claude wiring -------------------------------------------------------------

def _wire_claude_mcp(uv: str, mcp_script: str, *, remove: bool = False) -> Path:
    cfg_path = _claude_json_path()
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    if remove:
        servers.pop("brainspace", None)
    else:
        servers["brainspace"] = {
            "command": uv,
            "args": _uv_run_args(mcp_script),
        }
    data["mcpServers"] = servers
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def _wire_claude_hook(home: Path, uv: str, hook_script: str, *, remove: bool = False) -> Path:
    """Register (or remove) the PostToolUse hook in <CLAUDE_HOME>/settings.json.

    Uses the documented matcher/hooks shape. Idempotent: identifies our hook by the
    brainspace_posttooluse.py path in its command and replaces/removes only that entry.
    """
    settings_path = home / "settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    post = hooks.get("PostToolUse") if isinstance(hooks.get("PostToolUse"), list) else []

    cmd = _uv_run_cmd(uv, hook_script)

    # Drop any prior brainspace hook entries (match by script name) for idempotency.
    def _is_ours(entry):
        for h in entry.get("hooks", []):
            if "brainspace_posttooluse" in (h.get("command") or ""):
                return True
        return False

    post = [e for e in post if not _is_ours(e)]

    if not remove:
        post.append({
            "matcher": "*",  # all tools; the hook self-filters by BRAINSPACE_HOOK_TOOLS + size
            "hooks": [{"type": "command", "command": cmd}],
        })

    hooks["PostToolUse"] = post
    data["hooks"] = hooks
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return settings_path


# -- copilot wiring ------------------------------------------------------------

def _wire_copilot_mcp(home: Path, uv: str, mcp_script: str, *, remove: bool = False) -> Path:
    """Register the brainspace MCP server in <COPILOT_HOME>/mcp-config.json.

    Copilot's mcp-config.json uses the same ``mcpServers`` map shape as Claude. We
    write the stdio server entry; idempotent on the ``brainspace`` key.
    """
    cfg_path = home / "mcp-config.json"
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    if remove:
        servers.pop("brainspace", None)
    else:
        servers["brainspace"] = {
            "type": "stdio",
            "command": uv,
            "args": _uv_run_args(mcp_script),
            "tools": ["*"],
        }
    data["mcpServers"] = servers
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return cfg_path


# -- main ----------------------------------------------------------------------

def main() -> int:
    argv_host = ""
    uninstall = False
    positionals = []
    for arg in sys.argv[1:]:
        if arg.startswith("--host="):
            argv_host = arg.split("=", 1)[1]
        elif arg == "--uninstall":
            uninstall = True
        else:
            positionals.append(arg)

    host = _resolve_host(argv_host)
    uv = shutil.which("uv") or "uv"
    if not shutil.which("uv"):
        return _fail("`uv` not found on PATH — the brainspace server launches via uv. "
                     "Install uv (https://docs.astral.sh/uv/) and re-run.")

    home = _host_home(host)
    print(f"[brainspace] host: {host}")
    print(f"[brainspace] home: {home}")

    install_dir = _install_files(home)
    mcp_script = str((install_dir / "brainspace_mcp.py")).replace("\\", "/")
    hook_script = str((install_dir / "brainspace_posttooluse.py")).replace("\\", "/")
    uv_fwd = uv.replace("\\", "/")

    summary = ["[brainspace] done." if not uninstall else "[brainspace] uninstalled."]
    summary.append(f"  files:  {install_dir}")

    if host == "claude":
        cfg = _wire_claude_mcp(uv_fwd, mcp_script, remove=uninstall)
        settings = _wire_claude_hook(home, uv_fwd, hook_script, remove=uninstall)
        summary.append(f"  mcp:    {cfg} (server 'brainspace')")
        summary.append(f"  hook:   {settings} (PostToolUse auto-compress)")
        summary.append("  mode:   FULL — auto-compress hook + model-invoked tools.")
        summary.append("Restart Claude Code to activate. Tool outputs are auto-compressed; "
                       "the model can also call brainspace_compress / brainspace_retrieve.")
    else:
        cfg = _wire_copilot_mcp(home, uv_fwd, mcp_script, remove=uninstall)
        summary.append(f"  mcp:    {cfg} (server 'brainspace')")
        summary.append("  mode:   MCP-ONLY — Copilot CLI has no documented PostToolUse "
                       "output-rewriting hook, so compression is model-invoked (opt-in).")
        summary.append("Restart Copilot. Ask it to compress large outputs, or it calls "
                       "brainspace_compress / brainspace_retrieve as MCP tools.")

    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
