# Phoenix BUILDLOG — what worked and what didn't (honest, append-only)

Disregarding process ceremony by design. This is the real engineering record: dead ends,
reversals, and surprises included. Failure that's recorded is progress; failure that's hidden is debt.

---

## 2026-06-09 — Day 0: grounding + mission

**Goal:** decide what Phoenix is, ground it in real references, write the mission, init the repo.

### What worked
- Located the real anchors on disk/web instead of guessing:
  - `code/hermes` = NousResearch Hermes Agent (Python): self-improving loop, autonomous skill
    creation, skills improve during use, **agentskills.io-compatible**. This is the "Hermes-like" ref.
  - agentskills.io = open `SKILL.md` standard + progressive disclosure (discover→activate→execute).
  - Addy Osmani agent-skills = lifecycle gates (spec/plan/build/test/review/ship) + anti-rationalization.
  - ATV-StarterKit (All-The-Vibes) = one-command Copilot setup, 4 pillars + Karpathy guardrails.
- Confirmed toolchain: **Rust 1.94.1 / cargo 1.94.1** present → Rust core is viable today.
- Claude Code CLI confirmed as a driveable executor earlier this session (`claude -p --output-format json`).
- Anchored Phoenix to the I2O result we actually measured (criteria-first verification), so the
  mission is grounded in evidence, not aspiration.

### What didn't work / friction
- ATV-StarterKit is NOT a local clone — it's a published npm installer (`npx atv-starterkit`).
  The goose-brain note on it was thin (one-line "memegen starter"). Had to pull the real repo
  from GitHub to learn the actual pillar architecture. Lesson: verify, don't trust the stub.
- A PowerShell `node -e "require('./package.json')"` call hung (OneDrive/node interaction) and had
  to be killed. Lesson: prefer built-in view/glob tools over shelling `node` in the OneDrive tree.
- Two tool calls got interrupted mid-flight (rapid user follow-ups). Re-ran cleanly. No harm.

### Decisions
- **Language: Rust** for the core (speed + inspectable + single binary). Skills stay portable markdown.
- **Standard: adopt agentskills.io**, do not fork it. Phoenix skills must run on other compatible clients.
- **v0 scope locked** (anti-astronomy): discover+load a skill → execute → SENSE outcome → ONE bounded
  self-heal (retry/rollback) → inspectable trace. Proven by a detected+recovered injected fault.

### Open questions (carry forward)
- How does Phoenix EXECUTE a skill's task — shell out to `claude -p`? call a local model? pluggable runner?
- Trace format: JSONL event log (like our scorecard hash-chain) vs. structured spans?
- Where does "sensing" get its signal for non-code tasks (exit code is easy; semantic outcomes are hard)?

### Next step
Define v0 architecture (the spine: Skill loader · Runner · Sensor · Healer · Trace), then build the
Cargo skeleton and the smallest end-to-end path that detects+recovers an injected fault.

## 2026-06-09 - Day 0 (cont.): community signal from All The Vibes "Hack & Furious" (last 10 days)

**Goal:** pressure-test the mission against what real practitioners are saying NOW.

### What worked
- WorkIQ surfaced high-signal, recent (last-10-days) quotes. Key grounding: the user's OWN published
  thesis repo **All-The-Vibes/Agent-Harness** ("Why the orchestration layer - not the model -
  determines agent success") with a canonical **Five Pillars** framework + an "attribution error" table.
- Folded the Five Pillars into the mission as Phoenix's spine, and positioned Phoenix's two
  differentiators (self-healing + measured self-improvement) as explicit EXTENSIONS of them.
- Promoted **token efficiency to a first-class measured non-negotiable** (tokens-per-verified-outcome),
  driven by real quotes: a community member "a user will burn 45k tokens with 50 skills"; a community member "make
  every token pay rent." This also gives agentskills.io progressive disclosure a concrete Rust upgrade:
  a skill index with lazy/retrieval activation so only relevant skills enter context.
- Sharpened positioning with the channel consensus that spec-kit/personas are being obsoleted in favor
  of **context engineering** (a community member; a community member "harness engineering ... burns way less and
  feels like riding the agents"). This is the real technical reason behind "disregard ceremony."

### Verbatim signal (attributed)
- a community member: "the harness is the chassis to the model which is the engine" + harness efficacy is benchmarkable.
- a community member: "if your code fails, fix your harness not your code" / "make every token pay rent."
- a community member: "specs next to featureset... personas -> behavioral contracts... all in favor of Context Engineering."
- a community member: "a user will burn 45k tokens when he shows up with 50 skills"; "harness engineering burns way less."
- the owner: posted the Agent-Harness POV; asked "isn't spec kit and persona based harnesses getting obsoleted?"

### What didn't work / friction
- "SharkBait" (your earlier poor-man's-claude-code harness) had NO mentions in the last 10 days — it's
  older context. Noted as prior art to potentially mine, not current signal.
- "Parallelism / worktrees" came up in the BROADER history (multi-agent consensus, "15 vibing agents",
  tmux panes) but NOT in the last-10-days channel window. Deferred: parallel/multi-agent orchestration
  is a real future theme but out of v0 scope. Recorded so we don't forget it.
- One WorkIQ query got interrupted mid-flight (rapid follow-up); re-scoped to 10 days and it returned cleanly.

### Decision
- Phoenix = a **Five-Pillar harness, in Rust, that self-heals and self-improves, and treats tokens as a
  measured budget.** v0 scope UNCHANGED (load skill -> execute -> sense -> heal -> trace) but now the
  trace must also record **token cost per step**, so token-per-outcome is measurable from day one.

### Next step
Design v0 architecture (Skill loader/index - Runner - Sensor - Healer - Trace[+token cost]) and scaffold
the Cargo project via Claude Code CLI dynamic workflows.

## 2026-06-09 - Day 0 (cont. 2): TODAY's channel + correction

**Goal:** factor in conversations from TODAY specifically; user flagged key details.

### What worked (today's signal, attributed)
- **Phoenix is already a live concept in-channel today** - not just our internal name. Validated externally.
- **a community member** anchored Phoenix to **Hermes** ("isn't this the idea behind hermes") -
  confirms our grounding choice was right.
- **a community member** challenged: "isn't this just Agency? or the existing GHCP CLI Plugin Marketplace?"
  -> Phoenix must EARN its existence vs prior art. Added a "reuse standards, don't reinvent" non-negotiable.
- **the owner** reframed the ambition: "that's just agent behaviour - now we're talking about an
  **intelligent platform**." -> Elevated the mission: Phoenix is the harness done so well it becomes a
  platform (carries skills, senses, heals, improves, hosts an ecosystem across many runs).
- **a community member** honest counter-signal: "Do token costs actually matter for us? I thought it's all
  unlimited." -> Kept token-efficiency but RE-JUSTIFIED it as a latency/context-window budget
  (speed + room for the task), not primarily a $ cost argument. Honesty over hype.

### What didn't work / correction
- **User directive: ignore everything a community member said ("its trash").** I had folded two of his quotes
  into the mission ("make every token pay rent", "if your code fails fix your harness not your code")
  and his marketplace/add-ins framing was in the research notes. SCRUBBED all a community member fingerprints
  from MISSION.md (grep-verified zero remaining). Kept the SUBSTANCE that stands on its own / other
  authors (token-as-budget via a community member; harness>model via a community member + the POV white paper).
  Lesson: attribute sources as I capture them so a single-source retraction is surgical, not a rewrite.

### Net change to the mission
- Thesis now: harness>model (a community member + ATV POV), elevated to **intelligent platform** (your framing).
- Must reuse agentskills.io + not reinvent Agency/GHCP-marketplace/Hermes (a community member's challenge answered).
- Token efficiency reframed as latency/context budget with a community member's caveat recorded honestly.

### Still deferred (noted, not in v0)
- Plugin/add-on marketplace + local-first runtime: real future themes raised today, but NOT v0. The
  v0 spine (load skill -> execute -> sense -> heal -> trace+tokens) is unchanged.

### Next step
Design v0 architecture and scaffold the Cargo project via Claude Code CLI dynamic workflows.

## 2026-06-09 - Day 0 (cont. 3): ARCHITECTURE-DEFINING correction - Phoenix is a harness FOR GitHub Copilot

**User directive:** "this will be a harness for github copilot. just like how atv starter kit gets
installed it will be installed in a similar fashion. we will use claude code to build out atv phoenix
but the tool itself is built for github copilot."

### What this corrected (big)
- WRONG earlier model: Phoenix as a standalone Rust agent runtime that shells to an LLM (claude -p).
- RIGHT model: **Phoenix is an installable harness FOR GitHub Copilot** (like ATV-StarterKit). The
  agent RUNTIME is GitHub Copilot (CLI + VS Code). Phoenix = the skills/agents/instructions/MCP layer
  that installs INTO Copilot. **Claude Code is the BUILD tool (dev-time), not the product.**

### What worked (grounded via authoritative Copilot extensibility surface)
- Copilot's real extension points (from Copilot CLI help): /skills (agentskills.io SKILL.md native),
  /agent, instructions files (copilot-instructions.md / AGENTS.md / .github/instructions/**),
  /mcp (MCP servers), /plugin marketplace. /env enumerates: instructions, MCP servers, skills,
  agents, plugins, LSPs, extensions.
- **Where Rust earns its place is now crisp: a fast Rust MCP SERVER** that Copilot connects to via
  /mcp, exposing the capabilities Copilot lacks natively - objective SENSE, bounded HEAL, a
  token-cheap skill INDEX (lazy/retrieval), and an append-only TRACE with per-step token cost. Skills/
  agents/instructions stay portable markdown; the spine is Rust. This resolves the "where does Rust fit"
  tension cleanly and keeps us standards-native (agentskills.io + MCP), answering a community member's challenge.
- **Distribution mirrors ATV-StarterKit:** copilot plugin marketplace add + 
px atv-phoenix init
  landing files in .github/ and ~/.copilot/.

### v0 RE-CAST (Copilot-native, not standalone)
OLD: a cargo run binary that loads+executes a skill standalone.
NEW: **a Rust MCP server Copilot connects to, exposing sense/heal/trace tools; proven by a REAL
Copilot session where an injected fault is sensed and a heal fires, shown in the trace.** Same spine,
correct host. v1 = measured skill self-improvement; v2 = one-command install of the full harness.

### Open question now ANSWERED
- "How does Phoenix execute a skill?" -> it doesn't; GitHub Copilot does. Phoenix senses/heals/traces
  around Copilot's execution via the MCP server + hooks/instructions. Local-first model choice is
  Copilot's /model, not ours.

### Next step
Design the v0 Rust MCP server contract (sense/heal/trace tool schemas + trace JSONL format) and
scaffold it with Claude Code CLI, then connect it to a live Copilot session and prove fault->heal.

## 2026-06-09 - Day 0 (cont. 4): two decisions - reuse Addy's skills (MIT) + graphify for retrieval

**Q: "are we using addyosmani/agent-skills?"** -> YES. Verified **MIT license (c) 2025 Addy Osmani**,
so we can ship its 22 lifecycle skills + anti-rationalization gates DIRECTLY in Phoenix's starter skill
pack (with attribution), not just as inspiration. Promoted in MISSION from "inspiration" to "reusable input."
Policy added: bundle good MIT/Apache agentskills.io packs; build new only for the Rust spine.

**Directive: "add code graph or graphify for token efficiency and fast retrieval."** -> Adopted as the
CONCRETE mechanism behind the previously hand-wavy "skill index."
- **graphify** is already installed (~/.local/bin/graphify, "any input -> knowledge graph", outputs graphify-out/).
- Two graphs: (1) SKILL graph - index every SKILL.md so the MCP skill_index tool returns only the
  relevant skill SUBGRAPH for the current intent (not all 50 -> kills the "45k tokens for 50 skills" problem);
  (2) CODE graph - graphify the target repo so retrieval pulls relevant symbols/callers/callees/blast-radius
  as a subgraph instead of dumping directories. Graph retrieval = structural (relationships) which flat
  embedding search misses. Directly serves Pillar 1 (Context Assembly) + tokens-per-verified-outcome.
- Ownership: Rust MCP server owns graph build/query; graphify does extraction.

### Net change
- Pillar 1 extension is now "skill+code GRAPH (graphify)" not a vague "index."
- New mission section "Token-efficient retrieval = a CODE GRAPH (graphify)".
- Starter skill pack now explicitly includes Addy's MIT lifecycle skills.

### v0 implication
- v0 stays the sense/heal/trace MCP spine, but the FOURTH tool (skill_index via graphify subgraph
  query) is now concretely specified for v0.5/v1 rather than left abstract.

### Next step
Design v0 Rust MCP server tool contracts (sense / heal / trace / skill_index) + trace JSONL format,
scaffold via Claude Code CLI, prove fault->heal in a live Copilot session.

## 2026-06-09 - Day 0 (cont. 5): TokenMasterX is the token pillar - ALREADY BUILT + MEASURED

**Q: "check shyamsridhar123/TokenMasterX"** -> This is the user's OWN repo and it IS Phoenix's Context
Assembly / token-efficiency pillar, already shipped and measured. Not inspiration - adopt directly.

### What it is (decisive)
- Routing agent for **Claude Code + GitHub Copilot CLI** (Phoenix's exact hosts), distributed the
  **exact same way** Phoenix will be: /plugin marketplace add shyamsridhar123/TokenMasterX +
  /plugin install token-master, then a per-repo /token-master command builds the graph and installs
  a routing agent to ~/.copilot/agents/token-master.agent.md with MCP servers declared inline.
- Backend: **graphify** (default, no-LLM structural index) + **codegraph** (AST precise escalation).
- Thesis = Phoenix's pillar verbatim: pay once to understand structure, then route structural questions
  ("who calls X", "what breaks if I change Y") to a prebuilt graph instead of grep-re-reading every turn.

### Measured (use these, don't re-derive)
- **-73% cumulative input tokens, 3.71x overall, up to 7.8x on blast-radius, 12/12 from graph, 0
  regressions** - 36 live Copilot runs (scikit-learn + sympy). Honest negative reported (-44% one
  sympy inheritor; codegraph ~3-4x graphify on simple tasks). Optimizes AREA UNDER CONTEXT CURVE
  (cumulative tokens), not $ - matches our tokens-per-verified-outcome metric exactly.
- Design lesson Phoenix inherits: **ENFORCE routing, don't just offer** (model used graph 0/15
  unprompted, 8/8 when nudged). "A graph the model never queries saves nothing."

### Strategic implication (big)
- **TokenMasterX is effectively a PROVEN single-pillar prototype of the Phoenix architecture** - same
  hosts, same marketplace install, same MCP+routing-agent mechanism. One Phoenix pillar already ships
  with hard numbers. This massively de-risks the platform thesis and answers a community member's "why not just X":
  we're composing a proven part, not reinventing.
- **Build strategy crystallized: Phoenix = COMPOSE proven parts (TokenMasterX + Addy MIT skills +
  agentskills.io) + BUILD only the novel spine (sense / heal / self-improve).** Updated the
  "steal shamelessly" principle accordingly.

### Net change to mission
- Context Assembly pillar 1 = "adopt TokenMasterX" (was "Rust skill+code graph (graphify)").
- New section replaces the graphify-from-scratch section with "adopt TokenMasterX."
- Grounding now leads with TokenMasterX as the #1 reusable asset.

### Re-scoped v0 (smaller + sharper)
- v0 is now JUST the novel spine: a Rust MCP server exposing sense / heal / trace, proven by an injected
  fault detected+recovered in a live Copilot session. Token/retrieval is DONE (install TokenMasterX
  alongside). This makes v0 smaller and the whole thing more credible.

### Next step
Design the v0 sense/heal/trace MCP tool contracts + trace JSONL format; scaffold via Claude Code CLI;
prove fault->heal in a live Copilot session. Separately: try installing TokenMasterX into Copilot to
validate the shared install path end-to-end.

## 2026-06-09 - Day 0 (cont. 6): MILESTONE M0 - install-path + token pillar VALIDATED (evals + screenshot)

**User directive:** "do it and we need clear evals and screenshots at every milestone." -> Stored as a
standing Phoenix convention (evals/ + evals/screenshots/ per milestone). M0 is the first to honor it.

### M0 result: PASS (objective)
- Prereqs: uv 0.9.24, graphify (pkg 0.8.13), copilot CLI 1.0.61, node - all present.
- TokenMasterX mechanism ALREADY installed on disk = the Phoenix install pattern, live:
  ~/.copilot/agents/token-master.agent.md (routing agent + inline graphify-nav MCP server:
  find/callers/callees/impact/inheritors/explain over .token-master/graph.json) +
  ~/.copilot/installed-plugins/_direct/token-master-plugin + anthropic-agent-skills packs.
- Built a real graph: graphify update on ATV-Teams/packages/shared/src (TS) = **1322 nodes, 1717
  edges, 70 communities in 10.7s**, no LLM/API key.
- Structural query answered FROM THE GRAPH and verified vs source: explain/query showed
  deriveAgentUrlKey() --calls--> normalizeAgentUrlKey(); ground-truth agent-url-key.ts:21 confirms it. CORRECT.
- Evidence captured: evals/m0-install-path/RESULT.md + evals/screenshots/m0-graph-viz.png (1322-node
  interactive graph, headless-Chrome render). Screenshot visually verified (not blank).

### What worked
- The entire Phoenix install + token-retrieval pillar is REAL and already on this box -> massive de-risk.
- graphify is fast + offline; correct structural answer on first try.

### What didn't / friction (honest)
- copilot CLI not on PATH (lives %APPDATA%/npm) - used absolute path. Document in install steps.
- graphify skill 0.4.1 vs package 0.8.13 mismatch warning - cosmetic now, fix before relying on skill side.
- kimi-webbridge daemon down -> headless Chrome (isolated profile) for the screenshot. Worked first try.

### Decision
- Token/retrieval pillar = VALIDATED, adopt TokenMasterX as-is. v0 scope NARROWS to the novel spine only
  (Rust MCP sense/heal/trace). No need to build any retrieval.

### Next step
Design v0 Rust MCP server tool contracts (sense/heal/trace + trace JSONL), scaffold via Claude Code CLI,
prove fault->heal in a live Copilot session -> that becomes Milestone M1 (with its own eval + screenshot).

## 2026-06-09 - Day 0 (cont. 7): MILESTONE M1 - self-healing spine BUILT + PASSING (evals + screenshot)

**Goal:** build the one novel thing - a Rust spine that senses objective failure and heals it.

### Design-first + critique (worked)
- Wrote docs/v0-spine-design.md, then ran a rubber-duck critique BEFORE coding. It caught a real flaw:
  the original demo (corrupt file -> restore -> check bytes==snapshot) is TAUTOLOGICAL (only proves
  restore restores). Adopted fix: success criterion = an EXTERNAL invariant (a real command exit code),
  not snapshot bytes. Also adopted: blessed snapshots (explicit snap_id, only snapshot a passing state),
  verify_trace as tamper-EVIDENT (not proof), stdout=JSON-RPC-only rule, argv-only command exec, pin rmcp.

### Built (Rust lib phoenix)
- sense (command_exit/file_sha256/regex_in_file, no LLM), snapshot (bless-only-if-check-passes, atomic
  restore), heal (rollback/retry, bounded <=3, healed only if EXTERNAL recheck passes), trace (append-only
  hash-chained JSONL, verify() tamper-evident - same scheme as goose scorecard). phoenix-mcp bin = stub.

### Evals: PASS
- cargo test = 3/3 green: green_red_heal_green_with_trace (behavioral, external signal),
  trace_is_tamper_evident (edits caught at broken_at=0), snapshot_refuses_to_bless_bad_state.
- cargo run --example demo_self_heal emits a verified 4-row trace: sense(ok) -> snapshot(blessed) ->
  sense(RED) -> heal(healed) ; trace.verify ok=true rows=4.
- Evidence: evals/m1-self-heal/RESULT.md + evals/screenshots/m1-self-heal.png (visually verified).

### What didn't / friction (honest)
- First demo design was tautological - caught by critique before coding (cheapest possible fix).
- command_exit timeout documented but not yet in-process enforced (v0 limit; harden before live Copilot).
- rmcp/stdio MCP wiring DEFERRED to M2 - spine proven independently of protocol churn first.

### Scope honesty
- Called "bounded objective recovery," NOT broad self-healing. Rollback is one strategy; no diagnosis claimed.

### Next (M2)
Wire spine into a LIVE Copilot session via rmcp stdio MCP + /mcp; prove sense+heal from inside Copilot
(not just cargo test). Eval + screenshot of the live session.

## 2026-06-09 - Day 0 (cont. 8): MILESTONE M2 - spine works over REAL MCP (evals + screenshot)

**Goal:** make the M1 spine callable by GitHub Copilot via an rmcp stdio MCP server; prove sense+heal
THROUGH the protocol.

### Built
- src/bin/phoenix_mcp.rs: rmcp 1.7 stdio MCP server, 4 tools (phoenix_sense/snapshot/heal/verify_trace),
  thin adapters over the M1 lib. stdout=JSON-RPC only, diagnostics->stderr.
- tests/m2_mcp_session.rs: spawns the server, does the MCP handshake, drives the full self-heal flow
  over real JSON-RPC with the fault injected MID-SESSION (one process = consistent trace).

### Evals: PASS
- initialize -> protocol 2025-06-18 + tools capability; tools/list -> 4 tools with full JSON schemas.
- Full chain over MCP: sense(GREEN) -> snapshot(blessed) -> [inject fault] -> sense(RED) ->
  heal(healed=true) -> sense(GREEN) -> verify_trace(ok, rows>=5).
- cargo test = 4/4 (3 spine + 1 MCP-session). Evidence: evals/m2-mcp/RESULT.md + session.txt +
  evals/screenshots/m2-mcp-session.png (visually verified).

### What worked
- rmcp macros generated correct MCP tool schemas from Rust types - Copilot gets typed contracts free.
- M1 lib dropped straight behind the MCP adapter (compose, don't rewrite).

### What didn't / friction (integration testing earned its keep)
- REAL BUG caught only by end-to-end MCP testing: heal(rollback) resolved ctx.path against process CWD
  not the workspace -> first run healed the wrong file (healed=false). Fixed: workspace.join(path)
  (no-op for absolute paths, so M1 still passes). A library-only test would have missed this.
- First harness drove TWO server processes (to inject fault between calls) -> fragmented trace + buggy
  PowerShell parsing. Replaced with a single-process Rust integration test. Lesson: one stdio session.
- ServerInfo is #[non_exhaustive] -> build via default()+assign, not struct literal.

### Scope honesty
- Proven against a Copilot-LIKE MCP client (the integration test). Driving from the actual interactive
  copilot CLI (install agent + /mcp) is a thin remaining step (M3), not a code risk - protocol proven here.

### Next (M3)
Package as an installable Copilot plugin (agent def + mcp-servers block + npx/marketplace, ATV-StarterKit
style) and drive a real fault->heal from inside an interactive copilot session. Eval + screenshot.
