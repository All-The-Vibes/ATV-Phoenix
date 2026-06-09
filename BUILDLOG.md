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
