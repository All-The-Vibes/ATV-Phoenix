# Long-horizon agent design — Anthropic & OpenAI Codex (research notes)

Research grounding for Phoenix's autonomous trio (`phoenix-goal` + `phoenix-ralph` + `phoenix-auto`).
How the major labs design for **long-running / long-horizon** agent tasks, with verified citations.
Direct quotes are verbatim from the retrieved pages; unverifiable items are flagged at the end.

---

## Part 1 — Anthropic

**Building Effective Agents** — https://www.anthropic.com/engineering/building-effective-agents
- **Evaluator-optimizer loop:** *"one LLM call generates a response while another provides evaluation and feedback in a loop… particularly effective when we have clear evaluation criteria, and when iterative refinement provides measurable value."*
- **Orchestrator-workers:** *"a central LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results… well-suited for complex tasks where you can't predict the subtasks needed (in coding, for example, the number of files that need to be changed…)."*
- **Ground truth each step:** *"it's crucial for the agents to gain 'ground truth' from the environment at each step (such as tool call results or code execution) to assess its progress."*
- **Stopping conditions:** *"it's also common to include stopping conditions (such as a maximum number of iterations) to maintain control."*
- **Code is verifiable:** *"Code solutions are verifiable through automated tests; Agents can iterate on solutions using test results as feedback… Output quality can be measured objectively."*
- **Sandbox:** *"extensive testing in sandboxed environments, along with the appropriate guardrails."*

**Best practices** — https://code.claude.com/docs/en/best-practices
- **Runnable verifier:** *"Give Claude a check it can run: tests, a build, a screenshot to compare. It's the difference between a session you watch and one you walk away from… Give Claude something that produces a pass or fail, and the loop closes on its own."*
- **Four escalating grades of verifier:** prompt-inline → **`/goal` condition** (*"a separate evaluator re-checks after every turn"*) → Stop hook (deterministic gate) → verification subagent (*"a fresh model try to refute the result, so the agent doing the work isn't the one grading it"*).
- **Explore → Plan → Implement → Commit** workflow.
- **Evidence-based completion:** *"Have Claude show evidence rather than asserting success: the test output, the command it ran and what it returned… it works for sessions you weren't watching."*

**Agent SDK — agent loop / sessions / subagents**
- **Automatic compaction** (https://code.claude.com/docs/en/agent-sdk/agent-loop): *"When the context window approaches its limit, the SDK automatically compacts the conversation: it summarizes older history to free space… Persistent rules belong in CLAUDE.md… because CLAUDE.md content is re-injected on every request."*
- **Subagents / context isolation** (https://code.claude.com/docs/en/agent-sdk/subagents): *"Each subagent runs in its own fresh conversation… the parent receives a concise summary, not every file the subagent read."* `maxTurns` bounds each agent.
- **Sessions resume/fork/continue** (https://code.claude.com/docs/en/agent-sdk/sessions): SDK writes session to disk; *"Resume session {session_id} to continue"* after `error_max_turns` / `error_max_budget_usd`.

**Memory** — https://code.claude.com/docs/en/memory
- *"Each Claude Code session begins with a fresh context window. Two mechanisms carry knowledge across sessions: CLAUDE.md files… Auto memory: notes Claude writes itself."* AGENTS.md import supported.

**Claude 4 announcement** — https://www.anthropic.com/news/claude-4
- *"sustained performance on long-running tasks that require focused effort and thousands of steps, with the ability to work continuously for several hours."* Rakuten: a *"refactor running independently for 7 hours."*

---

## Part 2 — OpenAI Codex

**Cloud environments** — https://developers.openai.com/codex/cloud/environments
- Per-task isolated container: *"Codex creates a container and checks out your repo… runs your setup script… The agent runs terminal commands in a loop. It edits code, runs checks, and tries to validate its work. If your repo includes AGENTS.md, the agent uses it to find project-specific lint and test commands… it shows its answer and a diff of any files it changed."*
- *"Agent internet access is off by default."* Container caching up to 12h for warm restarts.

**Prompting** — https://developers.openai.com/codex/prompting
- **`/goal` mode:** *"Goal mode gives Codex a persistent objective to work toward across a longer task. Use it when the work may take many steps, or when Codex needs a clear definition of done that it can keep checking as it works. When you set a goal, the goal text acts as both the starting prompt and the completion criteria. Codex uses it to decide what to do next and whether the task is complete."*
- *"Write goals so Codex can tell whether it has succeeded. Good goals include a specific outcome, measurable target, or test criteria."*
- **Context compaction:** *"For longer tasks, Codex may automatically compact the context by summarizing relevant information… With repeated compaction, Codex can continue working on complex tasks over many steps."*
- **Decompose:** *"Codex handles complex work better when you break it into smaller, focused steps. Smaller tasks are easier for Codex to test."*
- **Verify:** *"Codex produces higher-quality outputs when it can verify its work. Include steps to reproduce an issue, validate a feature, and run linting and pre-commit checks."*

**Workflows** — https://developers.openai.com/codex/workflows
- Local `/plan` → cloud delegation for large refactors; *"design carefully (local context)… then outsource the long implementation to a cloud task."*

**GitHub integration** — https://developers.openai.com/codex/integrations/github
- AGENTS.md review guidelines; diff/PR as the verifiable output artifact.

**Agents SDK — sandboxes** — https://developers.openai.com/api/docs/guides/agents/sandboxes
- **Harness vs compute split:** *"The harness is the control plane around the model: it owns the agent loop, model calls, tool routing, handoffs, approvals, tracing, recovery, and run state. Compute is the sandbox execution plane."*
- **RunState / session state / snapshot** for resumable work; **`Compaction`** is a named `SandboxAgent` capability: *"Long-running flows need context trimming."*
- *"Put longer task specs and repo-local instructions in workspace files such as `repo/task.md` or `AGENTS.md`."*

---

## Part 3 — Convergent patterns (both labs) → Phoenix mapping

| Pattern | Anthropic | OpenAI Codex | Phoenix |
|---|---|---|---|
| Persistent definition of done, re-checked each step | `/goal` condition; Explore→Plan→Implement→Commit | `/goal` mode (goal = prompt + completion criteria) | `phoenix-goal` writes frozen `done-check.json` before code |
| Decompose into verifiable subtasks | prompt chaining + gates | "break into smaller, focused steps" | `phoenix-plan` → `backlog.json`, each item an objective check |
| Objective completion signal, not self-judgment | "give Claude a check it can run" | "verify its work… run linting and tests" | `phoenix_sense` + gate ledger (`accept`: red→green) |
| Externalize state to filesystem | CLAUDE.md + auto memory | AGENTS.md / `task.md` workspace files | `.phoenix-ralph/` (backlog.json, progress.md, done-check.json) |
| Fresh context / compaction | automatic compaction; subagent fresh convo | repeated compaction over many steps | Ralph re-invokes `copilot -p` fresh each loop |
| Dynamic orchestration | orchestrator-workers | `/plan` → cloud delegation; subagents | `phoenix-auto` (state-sensing router) |
| Sandbox + bounded iteration | maxTurns/maxBudgetUsd; stopping conditions | container per task; internet off by default | Ralph driver budgets (`-MaxLoops`/`-MaxMinutes`/`-NoProgressStop`) |
| Persistent instruction file | CLAUDE.md (re-injected each request) | AGENTS.md | `phoenix.agent.md` agent definition + `PROMPT.md` (fixed per-loop instruction) |

**Where Phoenix diverges:** both labs' loops still terminate on a *subjective* signal — an LLM
evaluator/goal-check, or a diff a human reviews. Phoenix replaces it with `phoenix-mcp accept`:
completion is derived from a **tamper-evident, hash-chained trace** showing the acceptance check went
**red → green** for the same check and green now. A check never seen failing is rejected; a dishonest
edit breaks the chain. Opinion at the finish line becomes evidence — the property needed for
*unattended* long-horizon runs.

---

## Gaps / unverified

- No Anthropic "context engineering" blog post found at the guessed URLs (404); the compaction material
  lives in the Agent SDK docs instead.
- The OpenAI Codex launch blog (`openai.com/index/introducing-codex/`) is JS-rendered and not
  text-extractable; all Codex techniques here come from `developers.openai.com/codex/` docs.
- Codex `/goal` storage/re-injection mechanism is described behaviorally, not at the implementation
  level — treat as behaviorally accurate, mechanism inferred.
- No user-facing `maxTurns` equivalent confirmed for Codex cloud tasks (confirmed for Anthropic's SDK).
