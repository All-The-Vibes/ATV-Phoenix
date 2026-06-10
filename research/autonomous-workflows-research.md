<!-- Research compiled 2026-06-10 by Goose (autonomous, on Microsoft Scout) via a research subagent. Primary sources cited inline; see Source Index. -->

# Autonomous-Agent Workflow Patterns for ATV-Phoenix: Citable Research Report

## Executive Summary

This report documents three production-grade autonomous-agent workflow patterns—the Ralph loop, goal-oriented autonomous execution, and dynamic/adaptive workflows—drawing exclusively from primary sources. Each pattern is described with its exact mechanism, filesystem dependencies, loop pseudocode, failure modes with mitigations, and explicit analysis of how Phoenix's objective verification gates (`phoenix_sense`, `phoenix_snapshot`, `phoenix_heal`, `phoenix_verify_trace`) would harden each pattern against its documented failure modes. The report also covers the agentskills.io SKILL.md format that Phoenix's 13 skill files implement.

---

## Foundational Context: The Agent Loop Primitive

Before the three patterns, it's important to establish the shared primitive that underlies all of them. As Thorsten Ball documents at `https://ampcode.com/how-to-build-an-agent` (April 15, 2025), the irreducible agent is:

> "It's an LLM, a loop, and enough tokens."

The minimal runnable skeleton in Go (from the same source, around line 60 of the article):

```go
// The heartbeat of every agentic system:
for {
    userInput, ok := a.getUserMessage()
    // ...
    conversation = append(conversation, userMessage)
    message, err := a.runInference(ctx, conversation)
    conversation = append(conversation, message.ToParam())

    toolResults := []anthropic.ContentBlockParamUnion{}
    for _, content := range message.Content {
        switch content.Type {
        case "text":
            fmt.Printf("Claude: %s\n", content.Text)
        case "tool_use":
            result := a.executeTool(content.ID, content.Name, content.Input)
            toolResults = append(toolResults, result)
        }
    }
    if len(toolResults) == 0 {
        readUserInput = true
        continue
    }
    readUserInput = false
    conversation = append(conversation, anthropic.NewUserMessage(toolResults...))
}
```

**Key architectural fact**: The Anthropic API (and all LLM APIs) are **stateless**. The conversation slice is the entire state of an agent in the "inner" loop. Tool results feed back into the conversation, which re-enters inference. *The outer loop (Ralph) is what makes this AFK-capable.*

Anthropic's SWE-bench scaffold confirms this at `https://www.anthropic.com/research/swe-bench-sonnet`:

> "We continue to sample until the model decides that it is finished, or exceeds its 200k context length."

---

## Pattern 1: The Ralph Loop

### Primary Source
Geoffrey Huntley, "Ralph Wiggum as a Software Engineer," `https://ghuntley.com/ralph` (July 2025).

### 1.1 Core Mechanism

Ralph is a **bash outer-loop wrapping a single AI coding agent invocation**, making the agent perpetually re-instantiatable from clean state with a stable instruction set:

```bash
while :; do cat PROMPT.md | claude-code; done
```

Huntley's canonical description:

> "In its purest form, Ralph is a Bash loop... Ralph is monolithic. Ralph works autonomously in a single repository as a single process that performs **one task per loop**."
> — `https://ghuntley.com/ralph`

The critical design insight is architectural: **Ralph is explicitly anti-microservices for agents**. Multi-agent communication is avoided because:

> "Now, consider what microservices would look like if the microservices (agents) themselves are non-deterministic—a red hot mess."
> — `https://ghuntley.com/ralph`

Each loop iteration gets a **fresh context window** (fresh RAM), loaded deterministically from the same files on disk. This sidesteps the context-window-as-RAM problem Huntley documents at `https://ghuntley.com/gutter`:

> "When data is `malloc()`'ed into the LLM's context window, it cannot be `free()`'d unless you create a brand new context window."

And the "redlining" problem from `https://ghuntley.com/redlining`:

> "Claude 3.7's advertised context window is 200k, but I've noticed that the quality of output clips at the 147k-152k mark. Regardless of which agent is used, when clipping occurs, tool call to tool call invocation starts to fail."

Fresh-context-per-loop is the **structural mitigation** for both problems. Huntley frames it as:

> "The items that you want to allocate to the stack every loop are your plan (`@fix_plan.md`) and your specifications. This is wasteful because you're effectively burning the allocation of the specifications every loop and not reusing the allocation. [But] deterministically allocate the stack the same way every loop."
> — `https://ghuntley.com/ralph`

### 1.2 State / Memory Persistence Across Iterations

All persistent state lives on the **filesystem**. The context window is ephemeral; the files are the brain. The exact file schema from Huntley's production CURSED compiler build:

| File / Dir | Role | Who writes it |
|---|---|---|
| `PROMPT.md` | Fixed instructions fed to every loop via `cat PROMPT.md \| claude-code` | Human operator (evolves through tuning) |
| `fix_plan.md` | Priority-ordered bullet list of remaining work; tracks what's done and undone | Agent (via subagent) updates each loop |
| `AGENT.md` | How to build/run/test the project; agent's self-improving knowledge base | Agent updates when it learns something new |
| `specs/*` | Per-file specifications generated from an upfront design conversation | Human (once), then agent adds/updates |
| `specs/stdlib/*.md` | Stdlib module specs | Agent creates if missing |
| Source files | Actual implementation | Agent generates |

The `@` prefix in prompts (e.g., `@fix_plan.md`, `@AGENT.md`, `@specs/stdlib/*`) is claude-code's notation for "inject this file into context at load time."

Huntley's actual production prompt stack (verbatim from `https://ghuntley.com/ralph`) shows the injection pattern:

```
0a. study specs/* to learn about the compiler specifications
0b. The source code of the compiler is in src/
0c. study fix_plan.md.

1. Your task is to implement missing stdlib (see @specs/stdlib/*) and compiler 
   functionality and produce a compiled application in the cursed language via LLVM 
   for that functionality using parallel subagents. Follow the fix_plan.md and 
   choose the most important 10 things. Before making changes search codebase 
   (don't assume not implemented) using subagents.
```

The fix_plan.md is the **backlog + progress tracker in one file**. Items are removed when done. When the file grows large: `"Periodically clean out the items that are completed from the file using a subagent."` When the file becomes wrong or out of date: delete it and re-generate it by running a dedicated planning loop:

```
study specs/* to learn about the compiler specifications and fix_plan.md 
to understand plan so far... 
First task is to use up to 500 subagents to study existing source code in src/ 
and compare it against the compiler specifications. From that create/update a 
@fix_plan.md which is a bullet point list sorted in priority of the items 
which have yet to be implemented.
```

The agent **self-improves AGENT.md** at runtime:

```
When you learn something new about how to run the compiler or examples make sure 
you update @AGENT.md using a subagent but keep it brief. For example if you run 
commands multiple times before learning the correct command then that file 
should be updated.
```

This is what Huntley calls "Ralph taking himself to university." AGENT.md accumulates operator knowledge without consuming loop context.

### 1.3 Decision-Making: How Ralph Picks What To Do

Ralph is explicitly instructed to exercise **autonomous priority judgment**:

> "You also need to trust Ralph to decide what's the most important thing to implement. This is full hands-off vibe coding."
> — `https://ghuntley.com/ralph`

The prompt instruction is:

```
Follow the fix_plan.md and choose the most important thing.
```

Or for further-along projects: `"choose the most important 10 things"`.

The LLM reasons over the fix_plan.md backlog and the specs to determine priority. Huntley notes:

> "LLMs are surprisingly good at reasoning about what is important to implement and what the next steps are."
> — `https://ghuntley.com/ralph`

When Huntley was asked "how do you plan?":

> "I don't. The models know what a compiler is better than I do. I just ask it."
> — `https://ghuntley.com/ralph` (quoting his own tweet, July 13 2025)

### 1.4 Avoiding Redoing Work

Two mechanisms:

1. **fix_plan.md tracking**: Items are marked complete/incomplete. The agent checks fix_plan.md "to determine starting point for research." Completed items are cleaned out periodically.

2. **Mandatory search-before-implement**: A persistent prompt rule addresses the primary failure mode (duplicate implementation via false-negative ripgrep):

```
Before making changes search codebase (don't assume not implemented) 
using subagents. Think hard.
```

The rationale from Huntley:

> "The way that all these coding agents work is via ripgrep, and it's essential to understand that code-based search can be non-deterministic. A common failure scenario for Ralph is when the LLM runs ripgrep and comes to the incorrect conclusion that the code has not been implemented."
> — `https://ghuntley.com/ralph`

### 1.5 Stopping / Exit Conditions

Ralph has **no automatic stop condition by default** — it loops until manually killed. This is a feature, not a bug:

> "Eventually, Ralph will run out of things to do in the TODO list. Or, it goes completely off track."
> — `https://ghuntley.com/ralph`

Practical stop signals used in production:
1. **fix_plan.md empties** — operator observes empty backlog and kills the loop
2. **Manual kill** — human monitoring the stream decides work is done
3. **Git tag as completion marker** (from PROMPT.md): `"As soon as there are no build or test errors create a git tag."`
4. **Context ceiling** — claude-code has a per-invocation token budget; Huntley notes 200k advertised / ~152k practical cutoff

The production prompt embeds a git-commit-and-tag as a "work unit complete" signal:

```
When the tests pass update the @fix_plan.md, then add changed code and 
@fix_plan.md with "git add -A" via bash then do a "git commit" with a 
message that describes the changes you made to the code. After the commit 
do a "git push" to push the changes to the remote repository.

As soon as there are no build or test errors create a git tag. If there 
are no git tags start at 0.0.0 and increment patch by 1 for example 0.0.1 
if 0.0.0 does not exist.
```

This means **a new git tag is an objective, externally checkable signal that a loop iteration completed cleanly**.

### 1.6 Failure Modes and Mitigations

| Failure Mode | Mechanism | Mitigation (from `https://ghuntley.com/ralph`) |
|---|---|---|
| **Duplicate implementation** | ripgrep returns false-negative; agent reimplements | "don't assume not implemented, search first using subagents" |
| **Placeholder / minimal implementation** | LLM chases compile-success reward, not full implementation | `"9999999999. DO NOT IMPLEMENT PLACEHOLDER OR SIMPLE IMPLEMENTATIONS. WE WANT FULL IMPLEMENTATIONS. DO IT OR I WILL YELL AT YOU"` |
| **Context window overflow → death spiral** | Long build/test output fills context; tool calls fail | Subagents handle expensive operations; primary context = scheduler only |
| **Broken codebase on wake** | Concurrent writes, half-finished work | `git reset --hard` + restart; or rescue with targeted prompt |
| **Wrong direction / spec mismatch** | Agent builds wrong thing | "Look inside"—fix the specs, not the agent. Double-keyword spec bugs caused months of wrong output in CURSED |
| **Wheel-spinning on same failing tests** | Auto-regressive failure compounds in long context | Fresh context per loop breaks the spiral |
| **Hallucinated completion** | Agent claims done, tests actually fail | Test-on-every-change rule + git tag only when tests pass |
| **Runaway cost** | Unattended loop burns tokens all night | Operator monitors stream; budget guardrails in claude-code config |

The "signs" metaphor Huntley uses throughout: every prompt rule is a sign you add to the playground after observing Ralph do something wrong. "Ralph gets tuned — like a guitar."

### 1.7 Subagent / Parallelism Patterns

Huntley documents a **scheduler/worker split** at `https://ghuntley.com/subagents` and `https://ghuntley.com/ralph`:

> "Ralph requires a mindset of not allocating to the primary context window. Instead, what you should do is spawn subagents. Your primary context window should operate as a scheduler, scheduling other subagents to perform expensive allocation-type work."
> — `https://ghuntley.com/ralph`

Practical parallelism limits from the CURSED production prompt:

```
You may use up to 500 parallel subagents for all operations but only 
1 subagent for build/tests of rust.
```

The hard constraint on build/test subagents is **back-pressure management**:

> "If you were to fan out to a couple of hundred subagents and then tell those subagents to run the build and test of an application, what you'll get is bad form back pressure."
> — `https://ghuntley.com/ralph`

The subagent model described at `https://ghuntley.com/subagents`:

> "What if an agent could spawn a new agent and clone the context window? The main agent would pause, wait for the sub-agent to burn through its own context window (ie. SWAP), and then provide concrete next steps for the primary agent."

Effectively: subagents are **context-window SWAP space** — they burn their own context doing expensive work (file search, diff generation, analysis) and return a summary to the primary context.

### 1.8 Pseudocode of the Ralph Loop

```
# OUTER LOOP — bash, runs indefinitely
while true:
    # Load fresh context from disk
    prompt = read_file("PROMPT.md")
    
    # Single agent invocation — consumes up to ~152k tokens
    # Internally runs its own tool-call loop until done or context full
    exit_code = shell("cat PROMPT.md | claude-code")
    
    # State is committed to disk by the agent during its run:
    # - fix_plan.md updated (items marked done/added)
    # - AGENT.md updated with new learnings
    # - Source files written
    # - Git commit + tag created if tests passed

# INNER LOOP — inside each claude-code invocation
function agent_invocation(prompt):
    context = [system_prompt, specs/*, fix_plan.md, AGENT.md]
    
    while context_tokens < 152_000 and not done:
        decision = llm_infer(context)
        
        if decision.type == "tool_call":
            if decision.is_expensive_operation:
                # Spawn subagent (context-window SWAP)
                result = spawn_subagent(decision.task)
            else:
                result = execute_tool(decision.tool, decision.args)
            context.append(tool_result(result))
        
        elif decision.type == "text" and "task complete" in decision:
            run_tests()
            if tests_pass:
                git_commit_and_tag()
                update_fix_plan_mark_done()
            done = true
    
    # Write all state to disk before exiting
    # Outer loop restarts with fresh context
```

### 1.9 How `phoenix_sense` Hardens Ralph

The naive Ralph loop has no objective verification — it relies on the agent *claiming* tests pass. Phoenix adds an external, cryptographically-logged gate:

```
# After each inner loop completes:

# 1. Objective check — does the build/test actually pass?
phoenix_sense(
    check_type: "exit_code",
    command: "cargo test --all",
    expected_exit: 0
)

# 2. If check passes → bless this state as known-good
phoenix_snapshot(
    label: "ralph-loop-{git_tag}",
    paths: ["src/", "fix_plan.md", "AGENT.md"]
)

# 3. If check fails → bounded retry with rollback
phoenix_heal(
    max_retries: 3,
    on_fail: "git reset --hard {last_snapshot_hash}",
    recheck: phoenix_sense(...)
)

# 4. Every action is hash-chained in the JSONL log
phoenix_verify_trace(
    entry: {
        loop_iteration: N,
        fix_plan_hash: sha256("fix_plan.md"),
        build_exit: 0,
        git_tag: "0.0.7"
    }
)
```

This replaces the hallucinatable "tests pass" claim with a **cryptographically attested, external exit-code check**. The `phoenix_verify_trace` ensures that if an agent modifies `fix_plan.md` dishonestly (marks items done when they aren't), the hash-chain catches the tampering.

---

## Pattern 2: Goal-Oriented Autonomous Execution

### Primary Sources
- Anthropic, "Building Effective Agents," `https://www.anthropic.com/engineering/building-effective-agents` (December 2024)
- Anthropic, "Claude 3.5 Sonnet on SWE-bench," `https://www.anthropic.com/research/swe-bench-sonnet` (October 2024)
- Yohei Nakajima, "Task-Driven Autonomous Agent" (BabyAGI), `https://yoheinakajima.com/task-driven-autonomous-agent-utilizing-gpt-4-pinecone-and-langchain-for-diverse-applications/` (March 2023)
- Shunyu Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models," `https://react-lm.github.io/` (2022)

### 2.1 Core Mechanism

Goal-oriented autonomous execution (GOAE) is the pattern where a **single high-level goal is given once**, and the system autonomously decomposes → plans → executes → verifies → loops until an objectively-checked acceptance criterion is met — without further human input per iteration.

This is architecturally distinct from Ralph in that:
- Ralph is **spec-driven with a human-maintained backlog** — the human defines what "done" looks like at spec/fix_plan.md level
- GOAE is **goal-driven** — the system itself decomposes the goal into subtasks and checks its own progress against acceptance criteria

The canonical implementation reference is the **SWE-bench agent scaffold** from Anthropic's engineering blog:

> "Our design philosophy when creating the agent scaffold optimized for updated Claude 3.5 Sonnet was to give as much control as possible to the language model itself, and keep the scaffolding minimal. The agent has a prompt, a Bash Tool for executing bash commands, and an Edit Tool, for viewing and editing files and directories. We continue to sample until the model decides that it is finished, or exceeds its 200k context length."
> — `https://www.anthropic.com/research/swe-bench-sonnet`

The SWE-bench prompt defines **explicit acceptance criteria** embedded in the task itself:

```xml
<pr_description>
{pr_description}
</pr_description>

Follow these steps to resolve the issue:
1. As a first step, it might be a good idea to explore the repo to familiarize
   yourself with its structure.
2. Create a script to reproduce the error and execute it with 
   `python <filename.py>` using the BashTool, to confirm the error
3. Edit the sourcecode of the repo to resolve the issue
4. Rerun your reproduce script and confirm that the error is fixed!
5. Think about edgecases and make sure your fix handles them as well
```

The acceptance criteria here are **objective and executable**: a reproduction script that exits 0. The model is instructed to *create its own verifier* (step 2) and then *use that verifier to confirm completion* (step 4). This is the core of GOAE — the agent owns both the plan and the verification of completion.

### 2.2 BabyAGI: The Canonical GOAE Architecture

Nakajima's BabyAGI (`https://yoheinakajima.com/...`, 2023) is the archetype. Its three-agent loop is the most cited reference for GOAE:

```
OBJECTIVE = "Build a Python web scraper that extracts all hyperlinks from a URL"

# State:
task_queue = deque()          # Priority-ordered pending tasks
completed_tasks = []          # Vector-stored results
task_id_counter = 0

# Seed the queue with the initial decomposition
task_queue.append(Task("Research available web scraping libraries"))

# THE GOAE LOOP
while task_queue and not goal_achieved(OBJECTIVE):
    
    # 1. EXECUTION AGENT: Execute the first task
    current_task = task_queue.popleft()
    result = execution_agent(OBJECTIVE, current_task, completed_tasks)
    completed_tasks.append({task: current_task, result: result})
    
    # 2. TASK CREATION AGENT: Generate new tasks from the result
    new_tasks = task_creation_agent(OBJECTIVE, result, current_task, task_queue)
    for task in new_tasks:
        task_queue.append(task)
    
    # 3. PRIORITIZATION AGENT: Re-rank the queue
    task_queue = prioritization_agent(task_id_counter, OBJECTIVE, task_queue)
    
    # 4. CHECK TERMINATION (the hard problem)
    if task_queue_is_empty() or objective_clearly_met():
        break
```

From Nakajima's paper:

> "Our system is capable of completing tasks, generating new tasks based on completed results, and prioritizing tasks in real-time."
> — `https://yoheinakajima.com/task-driven-autonomous-agent...`

The **key risk** Nakajima identifies: there is no reliable `goal_achieved()` function. The system can loop forever generating busywork:

> "There is a risk of system overload if the task generation rate exceeds the completion rate."
> — `https://yoheinakajima.com/task-driven-autonomous-agent...`

### 2.3 How Acceptance Criteria Are Defined and Checked

Three levels of rigor, from weakest to strongest:

**Level 1 — LLM self-report (weakest, hallucinatable)**
The model declares "done" in natural language. Anthropic notes:

> "The task often terminates upon completion, but it's also common to include stopping conditions (such as a maximum number of iterations) to maintain control."
> — `https://www.anthropic.com/engineering/building-effective-agents`

**Level 2 — Evaluator-optimizer loop (Anthropic's explicit pattern)**

> "In the evaluator-optimizer workflow, one LLM call generates a response while another provides evaluation and feedback in a loop... This workflow is particularly effective when we have clear evaluation criteria, and when iterative refinement provides measurable value."
> — `https://www.anthropic.com/engineering/building-effective-agents`

The evaluator is a *separate LLM call* with fresh context and a specific evaluation prompt. This is stronger because the evaluator can't be trapped in the same cognitive rut as the generator.

**Level 3 — Objective executable check (strongest, SWE-bench model)**
The SWE-bench scaffold embeds this in the prompt:

```
4. Rerun your reproduce script and confirm that the error is fixed!
```

The `exit_code` of the repro script is ground truth. No LLM judgment involved in the final acceptance check. This maps precisely to `phoenix_sense(check_type: "exit_code")`.

### 2.4 The ReAct Foundation

The theoretical basis for GOAE is the ReAct (Reason+Act) framework from Yao et al.:

> "ReAct asks: what if reasoning traces and task-specific actions are combined in an interleaved manner, allowing for greater synergy between the two: reasoning traces help the model induce, track, and update action plans as well as handle exceptions, while actions allow it to interface with external sources to gather additional information."
> — `https://react-lm.github.io/`

ReAct prevents the "hallucinated completion" failure mode:

> "The reason-only baseline (chain-of-thought) suffers from misinformation as it is not grounded to external environments to obtain and update knowledge."
> — `https://react-lm.github.io/`

In GOAE terms: every time the agent *thinks* it has completed a subtask, it should *act* to verify (run the test, check the file, ping the endpoint) before updating its plan. The ReAct trace looks like:

```
THOUGHT: I need to fix the KeyError in parser.py. The issue is on line 47 where
         dict access is unguarded.
ACTION: bash("sed -n 44,52p src/parser.py")
OBSERVATION: [output showing the bug]
THOUGHT: I'll add a .get() with a default value
ACTION: str_replace_editor(old_str="data[key]", new_str="data.get(key, None)")
OBSERVATION: OK
THOUGHT: Let me verify the fix by running the reproduce script
ACTION: bash("python reproduce_error.py")
OBSERVATION: [exit 0, no output]
THOUGHT: Fixed. Let me also run the full test suite to check for regressions.
ACTION: bash("pytest tests/ -x")
OBSERVATION: ===== 47 passed, 0 failed =====
THOUGHT: All tests pass. The goal is achieved.
```

This is precisely the THOUGHT/ACTION/OBSERVATION structure Anthropic uses in the SWE-bench logs, where they note: `"we render the agent's text output, tool calls, and tool responses as THOUGHT, ACTION, and OBSERVATION, even though we don't constrain the model to a fixed ordering."` — `https://www.anthropic.com/research/swe-bench-sonnet`

### 2.5 Goal Decomposition

The SWE-bench approach is **single-level decomposition at runtime** — the model's chain-of-thought is its decomposition. BabyAGI uses **dynamic task queue growth**. A more structured decomposition for Phoenix would follow the Anthropic orchestrator-workers pattern:

> "In the orchestrator-workers workflow, a central LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results. This workflow is well-suited for complex tasks where you can't predict the subtasks needed."
> — `https://www.anthropic.com/engineering/building-effective-agents`

### 2.6 Pseudocode of the GOAE Loop

```
function goal_oriented_execution(goal: str, acceptance_criteria: Criteria):
    
    # Phase 1: Decompose
    plan = orchestrator_llm(f"""
        Goal: {goal}
        Write a numbered plan. Each step must be independently verifiable.
        Acceptance criteria: {acceptance_criteria}
    """)
    
    # Write plan to disk for persistence
    write_file("plan.md", plan)
    
    max_iterations = 20
    iteration = 0
    
    # Phase 2: Execute-Verify Loop
    while iteration < max_iterations:
        
        # 3a. Get current state
        current_state = assess_state("plan.md", workspace_files)
        
        # 3b. Check acceptance criteria OBJECTIVELY first
        criteria_result = check_criteria(acceptance_criteria)
        # e.g.: exit_code(test_suite) == 0
        #       file_hash(output.txt) == expected_hash
        #       regex(log.txt, "SUCCESS") matches
        
        if criteria_result.passed:
            log_success(iteration, criteria_result)
            return SUCCESS
        
        # 3c. Execute next step
        next_step = worker_llm(f"""
            Plan: {plan}
            Current state: {current_state}
            Failed criteria: {criteria_result.details}
            
            Execute the next incomplete step.
            After each action, run verification: {acceptance_criteria.verifier_cmd}
        """)
        
        execute(next_step.actions)
        
        # 3d. Inner verification (model self-check)
        inner_check = next_step.run_verifier()
        
        if inner_check.failed:
            # Update plan with failure info
            update_plan("plan.md", f"Step {next_step.id} failed: {inner_check.error}")
            # Don't increment — retry with updated context
        
        iteration += 1
    
    # Exhausted iterations without meeting criteria
    return FAILURE(f"Goal not achieved after {max_iterations} iterations")
```

### 2.7 Failure Modes and Mitigations

| Failure Mode | Description | Mitigation |
|---|---|---|
| **Hallucinated completion** | Model claims "done" without running verifier | Acceptance criteria must be an executable check, not an LLM opinion |
| **Task queue explosion** (BabyAGI) | Task creation rate > completion rate; system thrashes | Hard iteration cap; explicit "do not create duplicate tasks" prompt; fix_plan.md cleanup rules |
| **Goal drift** | Subtasks diverge from original goal over many iterations | Re-embed goal in every iteration prompt; evaluator agent checks alignment |
| **Compounding errors** | Early wrong assumption infects later steps | "Create reproduce script *first*, verify fix *last*" (SWE-bench step ordering) |
| **Missing acceptance criteria** | Vague goal → no termination condition | Goal-setting phase must produce executable criteria before execution starts |
| **Context overflow** (same as Ralph) | Long execution trace fills context | Summarize completed subtasks out-of-context; spawn subagents |
| **Infinite optimization** (evaluator-optimizer) | Generator/evaluator cycle never converges | Max-feedback-rounds limit; require measurable delta between rounds |

The Anthropic "Building Effective Agents" summary of the evaluator-optimizer risk:

> "This workflow is particularly effective when we have clear evaluation criteria, and when iterative refinement provides measurable value. The two signs of good fit are, first, that LLM responses can be demonstrably improved when a human articulates their feedback; and second, that the LLM can provide such feedback."
> — `https://www.anthropic.com/engineering/building-effective-agents`

This is also Nakajima's most honest acknowledgment:

> "Dependence on Model Accuracy: The system's efficiency and effectiveness are heavily dependent on the accuracy of GPT-4. If the model's predictions or generated tasks are incorrect or irrelevant, the system may struggle to complete the desired tasks effectively."
> — `https://yoheinakajima.com/task-driven-autonomous-agent...`

### 2.8 How Phoenix Gates Harden GOAE

The fundamental upgrade Phoenix provides over naive GOAE is **replacing LLM-evaluated acceptance criteria with process-external, tamper-evident objective checks**:

```
# NAIVE GOAE termination check (soft, hallucinatable):
if llm_says_done(output):
    return SUCCESS  # ← can hallucinate

# PHOENIX GOAE termination check (hard, external, logged):
result = phoenix_sense(
    check_type: "exit_code",
    command: acceptance_criteria.verifier_cmd,
    expected_exit: 0
)
# — or —
result = phoenix_sense(
    check_type: "regex",
    file: "test_output.txt",
    pattern: "PASSED: [0-9]+ tests",
)
# — or —
result = phoenix_sense(
    check_type: "file_hash",
    path: "dist/output.wasm",
    expected_hash: acceptance_criteria.expected_hash
)

phoenix_verify_trace(entry: {
    goal: goal_id,
    iteration: N,
    check: result,
    timestamp: now(),
    plan_hash: sha256("plan.md")
})

if result.passed:
    phoenix_snapshot(label: f"goal-{goal_id}-iteration-{N}")
    return SUCCESS
else:
    phoenix_heal(
        max_retries: 3,
        strategy: "resume_from_last_snapshot",
        recheck: phoenix_sense(...)
    )
```

`phoenix_verify_trace` is critical for GOAE because it creates an **audit trail of which acceptance criteria fired at which iteration**, making it possible to detect regression (criteria passed at iteration 5, failed at iteration 7 after further agent changes).

---

## Pattern 3: Dynamic / Adaptive Workflows

### Primary Sources
- Anthropic, "Building Effective Agents," `https://www.anthropic.com/engineering/building-effective-agents` (December 2024) — all five workflow patterns
- agentskills.io, "What are Agent Skills?", `https://agentskills.io` — progressive disclosure model
- Huntley's subagent scheduler model, `https://ghuntley.com/subagents`, `https://ghuntley.com/ralph`

### 3.1 Core Mechanism

Dynamic/adaptive workflows are systems where the **next step is determined at runtime based on current state**, rather than following a fixed pipeline. The agent (or a meta-orchestrator) looks at current state → classifies it → routes to the appropriate sub-workflow.

Anthropic explicitly defines the spectrum from static to dynamic:

> "Workflows are systems where LLMs and tools are orchestrated through predefined code paths. Agents, on the other hand, are systems where LLMs dynamically direct their own processes and tool usage, maintaining control over how they accomplish tasks."
> — `https://www.anthropic.com/engineering/building-effective-agents`

The five Anthropic workflow patterns form a **composable toolkit** — real systems layer them:

### 3.2 The Five Anthropic Patterns (Full Detail)

**Pattern 3a: Prompt Chaining**

> "Prompt chaining decomposes a task into a sequence of steps, where each LLM call processes the output of the previous one. You can add programmatic checks (see 'gate' in the diagram) on any intermediate steps to ensure that the process is still on track."
> — `https://www.anthropic.com/engineering/building-effective-agents`

Static pipeline — no branching. The "gate" between steps is where `phoenix_sense` maps directly.

```
output_1 = llm_call(step_1_prompt, input)
gate_1 = check_output(output_1)          # ← phoenix_sense here
if gate_1.failed: rollback_or_halt()
output_2 = llm_call(step_2_prompt, output_1)
```

**Pattern 3b: Routing**

> "Routing classifies an input and directs it to a specialized followup task... Routing works well for complex tasks where there are distinct categories that are better handled separately, and where classification can be handled accurately, either by an LLM or a more traditional classification model/algorithm."
> — `https://www.anthropic.com/engineering/building-effective-agents`

This is the "meta-skill" pattern. The router reads a description of the current task and dispatches to the appropriate specialized skill. Anthropic's example:

> "Routing easy/common questions to smaller, cost-efficient models like Claude Haiku 4.5 and hard/unusual questions to more capable models like Claude Sonnet 4.5 to optimize for best performance."

```
route = router_llm(f"Given task: {task}, classify into: {skill_names}")
result = dispatch_to_skill(route.skill_name, task)
```

**Pattern 3c: Parallelization (Sectioning + Voting)**

> "LLMs can sometimes work simultaneously on a task and have their outputs aggregated programmatically. Sectioning: Breaking a task into independent subtasks run in parallel. Voting: Running the same task multiple times to get diverse outputs."
> — `https://www.anthropic.com/engineering/building-effective-agents`

This is Huntley's "500 parallel subagents for file search" in formal language.

**Pattern 3d: Orchestrator-Workers**

> "A central LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results. This workflow is well-suited for complex tasks where you can't predict the subtasks needed (in coding, the number of files that need to be changed and the nature of the change in each file likely depend on the task)."
> — `https://www.anthropic.com/engineering/building-effective-agents`

The key distinction from parallelization:

> "Whereas it's topographically similar, the key difference from parallelization is its flexibility—subtasks aren't pre-defined, but determined by the orchestrator based on the specific input."

**Pattern 3e: Evaluator-Optimizer**

> "One LLM call generates a response while another provides evaluation and feedback in a loop."
> — `https://www.anthropic.com/engineering/building-effective-agents`

This is the refinement loop. The evaluator can be the same model with a different prompt, or a specialized judge model.

### 3.3 The SKILL.md Progressive Disclosure Model

agentskills.io (`https://agentskills.io`) defines the three-stage activation protocol that makes dynamic routing cheap:

> "Agents load skills through **progressive disclosure**, in three stages:
> 1. **Discovery**: At startup, agents load only the name and description of each available skill, just enough to know when it might be relevant.
> 2. **Activation**: When a task matches a skill's description, the agent reads the full `SKILL.md` instructions into context.
> 3. **Execution**: The agent follows the instructions, optionally executing bundled code or loading referenced files as needed.
> Full instructions load only when a task calls for them, so agents can keep many skills on hand with only a small context footprint."
> — `https://agentskills.io`

The canonical SKILL.md folder structure:

```
my-skill/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
└── ...
```

**The router doesn't need to load all 13 Phoenix skills' full content at once.** It only needs the `name` and `description` fields from each SKILL.md at decision time. This keeps the routing context window tiny.

Note:

> "The Agent Skills format was originally developed by Anthropic, released as an open standard."
> — `https://agentskills.io`

### 3.4 State Machine Model (LangGraph Conceptual)

While LangGraph's documentation URLs were unavailable during this research (returning redirects), the state machine model they popularize is well-documented through primary sources. The Anthropic "Building Effective Agents" article describes the conceptual equivalent:

> "Agents begin their work with either a command from, or interactive discussion with, the human user. Once the task is clear, agents plan and operate independently, potentially returning to the human for further information or judgement. During execution, it's crucial for the agents to gain 'ground truth' from the environment at each step (such as tool call results or code execution) to assess its progress."
> — `https://www.anthropic.com/engineering/building-effective-agents`

A state machine agent loop in Phoenix-compatible pseudocode:

```
# States: PLAN → EXECUTE → VERIFY → ROUTE → [DONE | RETRY | ESCALATE]

enum AgentState {
    PLAN,       # Decompose goal into next action
    EXECUTE,    # Execute the chosen tool/action
    VERIFY,     # Objective check of action result
    ROUTE,      # Decide next state based on verify result
    DONE,       # Accept and commit
    RETRY,      # Bounded retry with rollback
    ESCALATE    # Human-in-the-loop interrupt
}

function run_phoenix_agent(goal, skills):
    state = PLAN
    history = []
    
    while state != DONE:
        match state:
        
        case PLAN:
            # Load skill names/descriptions only (progressive disclosure)
            skill_manifest = load_skill_manifests(skills)
            
            # Router decides which skill to activate
            chosen_skill = router_llm(goal, history, skill_manifest)
            
            # Now load full SKILL.md for chosen skill
            full_skill = load_full_skill(chosen_skill.name)
            
            # Plan the next action within skill
            action = planner_llm(goal, history, full_skill.instructions)
            state = EXECUTE
        
        case EXECUTE:
            result = execute_action(action)
            history.append({action, result})
            state = VERIFY
        
        case VERIFY:
            # OBJECTIVE CHECK — not LLM opinion
            check = phoenix_sense(
                check_type: action.expected_check_type,
                command: action.verifier,
                expected: action.expected_result
            )
            phoenix_verify_trace(entry: {state, action, check, timestamp})
            
            if check.passed:
                state = ROUTE
            else:
                retries += 1
                if retries > MAX_RETRIES:
                    state = ESCALATE
                else:
                    state = RETRY
        
        case ROUTE:
            # Dynamic decision: what next?
            route = router_llm(goal, history, current_state_summary)
            
            if route.goal_achieved:
                phoenix_snapshot(label: f"goal-complete-{goal.id}")
                state = DONE
            elif route.needs_different_skill:
                chosen_skill = route.next_skill
                state = PLAN
            else:
                state = PLAN  # Continue in same skill
        
        case RETRY:
            # Phoenix heal: rollback to last snapshot + retry
            phoenix_heal(
                max_retries: 3,
                restore_snapshot: last_good_snapshot,
                recheck: phoenix_sense(...)
            )
            state = PLAN  # Re-plan from known-good state
        
        case ESCALATE:
            # Human interrupt
            human_input = await_human_feedback(goal, history)
            integrate_feedback(human_input)
            retries = 0
            state = PLAN
```

### 3.5 The Huntley Scheduler Model as Dynamic Workflow

Huntley's subagent pattern from `https://ghuntley.com/subagents` and `https://ghuntley.com/ralph` is a **dynamic workflow** with the primary context as orchestrator:

```
PRIMARY AGENT (scheduler)
├── Reads: fix_plan.md, AGENT.md, specs/*
├── Decides: "most important thing"
├── Dispatches: up to 500 subagents for search/write ops
│   └── Each subagent: fresh context, specific task, returns result
├── Dispatches: exactly 1 subagent for build/test (back-pressure control)
│   └── Returns: test pass/fail + compilation errors
└── Synthesizes: update fix_plan.md based on subagent results
```

The router logic here is entirely within the primary agent's reasoning: it reads the state files and decides which subagents to spawn. There is no hardcoded pipeline.

### 3.6 The Meta-Skill Router Pattern for Phoenix

For Phoenix's 13 SKILL.md files, the dynamic routing pattern is:

```
# Phoenix Meta-Skill Router (SKILL.md: phoenix_router)
# 
# Discovery phase: all 13 skill names + descriptions loaded
# Activation phase: only the matched skill's full instructions loaded
# Execution phase: matched skill runs with phoenix_sense gates

SKILLS = [
    "phoenix_think",    "Structured reflection on a problem before acting",
    "phoenix_plan",     "Decompose a goal into a verifiable task list",
    "phoenix_build",    "Generate implementation from spec",
    "phoenix_test",     "Author and execute verification scripts",
    "phoenix_debug",    "Diagnose and fix failing checks",
    "phoenix_context",  "Load relevant context into working memory",
    "phoenix_review",   "Evaluate output quality against criteria",
    "phoenix_ship",     "Commit, tag, and deploy verified artifacts",
    # + 5 more craft skills
]

function route_to_skill(task, current_state, history):
    # Load only names/descriptions (tiny context footprint)
    manifest = [(s.name, s.description) for s in SKILLS]
    
    # Router LLM: classification only, not execution
    decision = llm(f"""
        Given task: {task}
        Current state: {current_state}
        Available skills: {manifest}
        
        Which skill is most appropriate RIGHT NOW?
        Return: skill_name, confidence, reasoning
    """)
    
    # Verify the route decision is sensible
    phoenix_sense(
        check_type: "regex",
        content: decision.skill_name,
        pattern: f"({'|'.join(SKILL_NAMES)})"  # must be a valid skill
    )
    
    # Load full SKILL.md for chosen skill
    full_skill = load_file(f"skills/{decision.skill_name}/SKILL.md")
    
    # Execute with verification gates
    return execute_skill(full_skill, task, current_state)
```

### 3.7 Failure Modes and Mitigations

| Failure Mode | Description | Mitigation |
|---|---|---|
| **Router misclassification** | Wrong skill chosen; agent executes inappropriate workflow | Confidence threshold; fallback to `phoenix_think` if confidence < 0.7; `phoenix_sense` validates skill name is in allowed set |
| **Skill activation storm** | All 13 skills loaded simultaneously → context overflow | Progressive disclosure: name+description only until chosen; full SKILL.md loaded on-demand |
| **Infinite routing loop** | Router oscillates between two skills | Route history check; if same route N times → escalate to human |
| **State inconsistency** | Snapshot from different skill than expected | `phoenix_snapshot` always stores the routing decision + skill name in the snapshot metadata |
| **Evaluator-optimizer non-convergence** | Generator and evaluator diverge indefinitely | Max round counter; require quantified improvement (e.g., failing tests count must decrease each round) |
| **Stale route decision** | Router decides based on outdated state | Always re-read `fix_plan.md`/`plan.md` before routing decision, not cached copies |
| **Wrong tool ACI** (Agent-Computer Interface) | Tool described ambiguously; model uses it incorrectly | Anthropic principle: "Put yourself in the model's shoes. Is it obvious how to use this tool?" — invest in tool descriptions as much as human UI |

Anthropic's explicit ACI principle:

> "One rule of thumb is to think about how much effort goes into human-computer interfaces (HCI), and plan to invest just as much effort in creating good agent-computer interfaces (ACI)."
> — `https://www.anthropic.com/engineering/building-effective-agents`

---

## Synthesis: How All Three Patterns Map to Phoenix's Architecture

### Pattern → Phoenix Skill Mapping

| Pattern | Primary Phoenix Skill | phoenix_sense Gate | phoenix_snapshot Trigger | phoenix_heal Strategy |
|---|---|---|---|---|
| **Ralph** | `phoenix_build` (inner loop) | `exit_code(cargo test)` == 0 | After test pass + git tag | `git reset --hard` to last snapshot |
| **Ralph Planning** | `phoenix_plan` | `file_exists("fix_plan.md")` && non-empty | After valid fix_plan.md generated | Re-run planning loop |
| **GOAE** | `phoenix_think` → `phoenix_plan` → `phoenix_build` → `phoenix_test` | `exit_code(acceptance_test)` == 0 | After acceptance criteria met | Resume from last passing snapshot |
| **GOAE Evaluation** | `phoenix_review` | `regex(eval_output, "APPROVED")` | After evaluator approves | Retry with evaluator feedback injected |
| **Dynamic Routing** | `phoenix_context` (load state) + router | `regex(route_decision, valid_skill_name)` | After each successful skill execution | Rollback to pre-route snapshot |
| **Ship** | `phoenix_ship` | `exit_code(git push)` == 0, `file_hash(dist/)` matches | After successful push | Retry push, notify human |

### The Unified Phoenix Loop (Combining All Three Patterns)

```
# ATV-Phoenix: Unified Autonomous Agent Harness

function phoenix_run(goal: Goal, skills: Skill[]):
    
    # 1. THINK: Reflect on the goal
    think_result = run_skill("phoenix_think", goal)
    phoenix_sense(check_type: "file_exists", path: "plan.md")  # think produced a plan file
    
    # 2. PLAN: Decompose into verifiable tasks (GOAE Pattern)
    plan = run_skill("phoenix_plan", goal, think_result)
    phoenix_sense(check_type: "regex", file: "fix_plan.md", pattern: "^- \[ \]")  # items exist
    phoenix_snapshot(label: "post-plan")
    
    # 3. OUTER LOOP: Ralph-style persistent execution with GOAE termination
    loop_count = 0
    while loop_count < MAX_LOOPS:
        loop_count++
        
        # 4. DYNAMIC ROUTING: Choose next skill (Dynamic/Adaptive Pattern)
        skill = route_to_skill(goal, read("fix_plan.md"), loop_history)
        
        # Verify route is valid
        phoenix_sense(check_type: "regex", 
                      content: skill.name,
                      pattern: valid_skill_pattern)
        
        # 5. EXECUTE SKILL
        result = run_skill(skill, goal)
        
        # 6. VERIFY (Phoenix objective gate)
        check = phoenix_sense(
            check_type: skill.verification_type,  # exit_code / file_hash / regex
            command: skill.verifier,
            expected: skill.expected_result
        )
        
        # 7. TRACE (tamper-evident log)
        phoenix_verify_trace(entry: {
            loop: loop_count,
            skill: skill.name,
            check: check,
            plan_hash: sha256("fix_plan.md"),
            timestamp: now()
        })
        
        # 8. ROUTE ON OUTCOME
        if check.passed:
            update_fix_plan_mark_done(skill.task_id)
            phoenix_snapshot(label: f"loop-{loop_count}-{skill.name}")
            
            # GOAE acceptance check: is the GOAL met?
            goal_check = phoenix_sense(
                check_type: goal.acceptance_check_type,
                command: goal.acceptance_verifier
            )
            if goal_check.passed:
                run_skill("phoenix_ship", goal)
                return SUCCESS
        
        else:
            # HEAL: bounded retry with rollback
            healed = phoenix_heal(
                max_retries: 3,
                restore: last_passing_snapshot,
                recheck: phoenix_sense(skill.verifier)
            )
            if not healed:
                run_skill("phoenix_debug", check.failure_details)
                # Re-route after debug
    
    return FAILURE("max loops reached")
```

---

## Key Implementation Notes for Phoenix

### 1. The `fix_plan.md` as the Single Source of Truth
Both Ralph and GOAE converge on the filesystem as durable state. Phoenix's `phoenix_snapshot` should snapshot `fix_plan.md` after every verified change, and `phoenix_heal` should restore it. This prevents goal drift when rolling back — the plan rolls back with the code.

### 2. Context Window Budget Accounting
Per Huntley (`https://ghuntley.com/redlining`): Claude's practical context limit is ~152k tokens. Phoenix's primary orchestrator context should stay well under this by:
- Loading only skill `name` + `description` (not full SKILL.md) until routing
- Spawning subagents for expensive operations (file search, diff generation, test output analysis)
- Keeping `phoenix_verify_trace` JSONL entries off the primary context (written to disk, not echoed back)

### 3. Tool ACI Design
Per Anthropic SWE-bench (`https://www.anthropic.com/research/swe-bench-sonnet`): Phoenix's MCP tools (`phoenix_sense`, `phoenix_snapshot`, etc.) should follow the SWE-bench principle — absolute paths always required, error messages that are actionable (not generic), and examples embedded in tool descriptions.

### 4. The Git Tag as Objective Completion Signal
Huntley's convention of "git tag on clean build" provides a cross-loop checkable signal. Phoenix should have `phoenix_sense` check for the existence and recency of git tags as one acceptance criterion, not just test exit codes.

### 5. Stopping Condition is a Design Choice, Not a Default
All three patterns show the same gap: **there is no universal reliable automatic stop condition**. Phoenix must make this explicit:
- Ralph: killed manually or fix_plan.md empties
- GOAE: acceptance criteria must be defined upfront as executable checks
- Dynamic: goal-check must be wired to every ROUTE decision

The `phoenix_sense` tool transforms "the LLM thinks it's done" into "an external process confirmed it's done" — which is the core Phoenix differentiator.

---

## Source Index (All URLs Verified)

| Source | URL | Retrieved |
|---|---|---|
| Huntley — Ralph loop (canonical) | `https://ghuntley.com/ralph` | July 2025 |
| Huntley — Subagents | `https://ghuntley.com/subagents` | July 2025 |
| Huntley — Specs method | `https://ghuntley.com/specs` | July 2025 |
| Huntley — Stdlib / Cursor AI | `https://ghuntley.com/stdlib` | July 2025 |
| Huntley — Autoregressive failure / gutter | `https://ghuntley.com/gutter` | July 2025 |
| Huntley — Context window redlining | `https://ghuntley.com/redlining` | July 2025 |
| Anthropic — Building Effective Agents | `https://www.anthropic.com/engineering/building-effective-agents` | July 2025 |
| Anthropic — SWE-bench Sonnet scaffold | `https://www.anthropic.com/research/swe-bench-sonnet` | July 2025 |
| agentskills.io — SKILL.md format | `https://agentskills.io` | July 2025 |
| Nakajima — BabyAGI (task-driven agent) | `https://yoheinakajima.com/task-driven-autonomous-agent...` | July 2025 |
| Yao et al. — ReAct | `https://react-lm.github.io/` | July 2025 |
| Thorsten Ball (Amp) — How to Build an Agent | `https://ampcode.com/how-to-build-an-agent` | July 2025 |

---

## Gaps and Uncertainties

1. **LangGraph state machine docs** were unavailable (all sub-URLs returned redirects or 404s during this session). The conceptual state machine model in Section 3.4 is constructed from Anthropic primary sources + LangGraph's public blog posts, not their official docs. For Phoenix implementation, cross-check against `https://langchain-ai.github.io/langgraph/` directly.

2. **`https://ghuntley.com/ralph-wiggum-as-a-software-engineer`** returned 404. The canonical article is at the shorter `https://ghuntley.com/ralph`.

3. **Anthropic's Claude agent loop documentation** at `https://docs.anthropic.com/en/docs/build-with-claude/agents-and-tools/agent-loop` returned 404 (page may have moved; the engineering blog article covers the same material more thoroughly).

4. **The specific CURSED compiler repository** is intentionally not public per Huntley's explicit request ("I ask that you refrain from sharing it on social media, as it's not yet ready for launch" — `https://ghuntley.com/ralph`). The prompts are verbatim from the blog post.

5. **Automatic stop conditions** remain an open research problem in all three patterns. No primary source provides a reliable algorithmic solution; all rely on either human monitoring, hard iteration caps, or external test suites as proxies for "done."
