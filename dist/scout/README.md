# Phoenix on Microsoft Scout

Scout does **not** accept arbitrary external MCP servers (its server set is fixed: filesystem,
playwright, shell, workiq). So Phoenix ships for Scout as a **CLI the Scout agent calls via its shell
tool**, plus a Scout skill that teaches the verify-heal loop.

## Feasibility (spike result, 2026-06-09)
- ❌ External MCP server: not supported by Scout.
- ✅ Shell tool: Scout can run `phoenix-mcp <subcommand> '<json>'` and use the **exit code** directly.
- ✅ Skills system: `phoenix-self-heal.skill.md` registers the loop as a discoverable Scout skill.
- ✅ Same Rust binary as the Copilot build — no separate core.

## Install
1. Build the release binary (`cargo build --release --bin phoenix-mcp`) and put it on PATH (or use the
   full path in the skill).
2. Place `phoenix-self-heal.skill.md` where Scout discovers skills.
3. Set `PHOENIX_WORKSPACE` to the repo root before invoking (snapshots + trace land in `.phoenix/`).

## Why a CLI and not MCP here
The Phoenix core is host-agnostic. Copilot consumes it as an MCP server (`/mcp`); Scout consumes it as
a CLI (shell + skill). One binary, two adapters — the multi-host design the product promises.
