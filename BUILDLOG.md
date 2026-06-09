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
