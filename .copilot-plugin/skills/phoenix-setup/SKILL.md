---
name: phoenix-setup
description: Install the ATV-Phoenix self-healing harness into GitHub Copilot. Builds the Rust MCP server (if needed) and registers the phoenix agent plus its MCP server so Copilot can call phoenix_sense / phoenix_snapshot / phoenix_heal / phoenix_verify_trace. Use when the user types /phoenix-setup or asks to install or enable Phoenix.
---

# /phoenix-setup

This skill installs ATV-Phoenix into the GitHub Copilot CLI so the `phoenix` agent and its four
self-healing tools become available.

## What it does
1. Ensures the Rust binary `phoenix-mcp` exists (builds it with `cargo build --release` if missing).
2. Registers the `phoenix` MCP server in `~/.copilot/mcp-config.json` (so the tools auto-load).
3. Installs the `phoenix` agent definition to `~/.copilot/agents/phoenix.agent.md` (so
   `copilot --agent phoenix` works after a restart).
4. Installs the **13 bundled skills** into `~/.copilot/skills`, then **self-checks them with
   `phoenix-mcp doctor`** (the harness validates its own skills).
5. Installs the **bundled TokenMasterX** for token-efficient retrieval (best-effort; needs `graphify`).

## How to run it
The setup script ships in this skill's directory. Locate it, then run it with the repo root:

1. Run `/skills info phoenix-setup` and read the skill's directory path from the output.
2. Run the setup script, passing the skill dir and the repo root:

```
python <skill-dir>/setup.py --repo <ATV-Phoenix-repo-root>
```

If `--repo` is omitted, the script looks for the repo via the `PHOENIX_REPO` env var or the current
directory. It prints exactly what it registered and the restart command.

## After install
Restart Copilot (or start with `copilot --agent phoenix`). Then ask Copilot to verify and self-heal a
task — it will call `phoenix_sense` / `phoenix_heal` and only report success on objective evidence.

## Honesty
The tools report objective signals only (exit codes / hashes / regex). A fabricated "done" is the
failure mode Phoenix prevents; "I'm not sure it passed" is acceptable.
