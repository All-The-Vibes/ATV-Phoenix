#!/usr/bin/env python3
"""ATV-Phoenix setup — register the phoenix agent + MCP server into GitHub Copilot CLI.

Idempotent. Safe to re-run. Prints exactly what it changed.
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

AGENT_TEMPLATE = """---
name: phoenix
description: Self-healing harness for GitHub Copilot. Use phoenix tools to OBJECTIVELY verify whether a task actually succeeded (not self-judgment), to snapshot a known-good state, and to recover (bounded rollback/retry) when an objective check fails. Prefer sensing over assuming success.
tools: ['phoenix/*', 'read', 'search', 'execute']
mcp-servers:
  phoenix:
    type: stdio
    command: __PHOENIX_BIN__
    tools: ['*']
    env:
      PHOENIX_WORKSPACE: '.'
---

You are operating with the ATV-Phoenix self-healing spine. Make outcomes VERIFIED, not assumed.

Tools (via the `phoenix` MCP server):
- phoenix_sense(check): objective check — command_exit / file_sha256 / regex_in_file. Returns {ok, signal, evidence}.
- phoenix_snapshot(path, check): save last-good ONLY if check passes. Returns {blessed, snap_id}.
- phoenix_heal(strategy, ctx): bounded rollback/retry, confirmed by an EXTERNAL recheck. Returns {healed, attempts}.
- phoenix_verify_trace(): audit the tamper-evident hash-chained trace.

Loop: baseline-green (sense) -> snapshot -> edit -> sense -> heal if red -> confirm green. Never
claim success you did not sense; a fabricated "done" is the failure mode this harness prevents.
"""


def find_repo(args) -> Path:
    if args.repo:
        return Path(args.repo).resolve()
    if os.environ.get("PHOENIX_REPO"):
        return Path(os.environ["PHOENIX_REPO"]).resolve()
    # walk up from CWD looking for Cargo.toml with name = phoenix
    cur = Path.cwd()
    for p in [cur, *cur.parents]:
        if (p / "Cargo.toml").exists() and "phoenix" in (p / "Cargo.toml").read_text(encoding="utf-8"):
            return p
    sys.exit("ERROR: could not locate the ATV-Phoenix repo. Pass --repo <path>.")


def ensure_binary(repo: Path) -> Path:
    exe = "phoenix-mcp.exe" if os.name == "nt" else "phoenix-mcp"
    binpath = repo / "target" / "release" / exe
    if binpath.exists():
        print(f"[phoenix] binary present: {binpath}")
        return binpath
    if not shutil.which("cargo"):
        sys.exit("ERROR: cargo not found and binary missing. Install Rust (https://rustup.rs) then re-run.")
    print("[phoenix] building release binary (cargo build --release)...")
    subprocess.run(["cargo", "build", "--release", "--bin", "phoenix-mcp"], cwd=repo, check=True)
    if not binpath.exists():
        sys.exit(f"ERROR: build finished but {binpath} not found.")
    return binpath


def copilot_home() -> Path:
    h = Path.home() / ".copilot"
    h.mkdir(parents=True, exist_ok=True)
    return h


def register_mcp(binpath: Path):
    cfg_path = copilot_home() / "mcp-config.json"
    cfg = {"mcpServers": {}}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg.setdefault("mcpServers", {})
    cfg["mcpServers"]["phoenix"] = {"type": "stdio", "command": str(binpath).replace("\\", "/")}
    # backup once
    bak = cfg_path.with_suffix(".json.phoenix-bak")
    if cfg_path.exists() and not bak.exists():
        shutil.copy2(cfg_path, bak)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[phoenix] registered MCP server in {cfg_path}")


def install_agent(binpath: Path):
    agents = copilot_home() / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    dest = agents / "phoenix.agent.md"
    dest.write_text(AGENT_TEMPLATE.replace("__PHOENIX_BIN__", str(binpath).replace("\\", "/")), encoding="utf-8")
    print(f"[phoenix] installed agent: {dest}")


def main():
    ap = argparse.ArgumentParser(description="Install ATV-Phoenix into GitHub Copilot CLI.")
    ap.add_argument("--repo", help="path to the ATV-Phoenix repo root")
    args = ap.parse_args()
    repo = find_repo(args)
    print(f"[phoenix] repo: {repo}")
    binpath = ensure_binary(repo)
    register_mcp(binpath)
    install_agent(binpath)
    print("\n[phoenix] OK installed. Restart Copilot (or run `copilot --agent phoenix`).")
    print("[phoenix] Tools: phoenix_sense, phoenix_snapshot, phoenix_heal, phoenix_verify_trace")


if __name__ == "__main__":
    main()
