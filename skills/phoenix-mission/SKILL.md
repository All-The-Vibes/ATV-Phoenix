---
type: Phoenix Skill
name: phoenix-mission
description: Run an N-goal DAG under the Phoenix supervisor — dependency-ordered execution with worktree isolation, lease fencing, budgets, a durable run ledger, and per-goal trace chains, on the local machine or dispatched to GitHub Copilot cloud agents. Use when goals have prerequisites, when a failure must contain its blast radius instead of sinking the run, when you need an auditable record of what executed where, or when work should run on Copilot cloud agents instead of this machine. Use when the user says /phoenix-mission, "run the DAG", "dispatch to cloud agents", "supervisor", or gives goals with dependencies. For proving N goals DONE use phoenix-intent; for one goal use phoenix-goal.
license: MIT
---

# phoenix-mission — supervised DAG execution

`phoenix-goal` drives one goal. `phoenix-intent` decomposes an intent into N goals and proves the
composite. Neither one *schedules*: they run loops back to back and trust that nothing collides.

`phoenix-mission` is the scheduler. It takes goals with declared prerequisites and runs them under
the supervisor spine:

> **plan → admit under capacity → isolate → execute → ledger + chain → contain failure**

## Read this first: what `capacity` means

`capacity` is a **real parallelism limit**. Goals admitted together execute concurrently — one
thread per goal — and the supervisor never admits more than `capacity` at once. Four independent
goals at `capacity: 4` run at the same time; at `capacity: 1` they run one after another.

Only the goal's own work runs off the scheduler thread. Admission, leases, worktrees, budgets, the
run ledger, and the hash-chained traces are all settled on the scheduler thread between batches —
the chains are hash-linked, so concurrent appends would corrupt the record used to prove what
happened.

With `backend: "cloud"`, each goal is submitted and polled on its own thread, so cloud goals
genuinely overlap too.

What you get:

| Property | What it means |
|---|---|
| True concurrency | Up to `capacity` goals inside `execute` simultaneously |
| Dependency ordering | A goal runs only after every prerequisite **succeeded** |
| Contained failure | A failed goal blocks its dependents; unrelated branches still complete |
| Panic containment | A backend that panics fails its own goal; the mission still settles |
| Worktree isolation | Every executed goal gets an exclusive workspace path |
| Lease fencing | A stale holder cannot write over a goal it no longer owns |
| Budgets | Per-goal and mission-wide caps; the mission stops when the mission cap blows |
| Durable run ledger | One append-only entry per execution, with backend + cost + error |
| Per-goal trace chains | Each goal gets its own tamper-evident chain, verified independently |
| Cloud dispatch | Each goal can run on a GitHub Copilot cloud agent instead of this machine |

Results are joined in admission order, so `records` stays deterministic even though execution
overlapped. Do not infer timing from record order — read the ledger.

## When to use it

Reach for `phoenix-mission` when **any** of these is true:

- Goals have real prerequisites and running them in the wrong order corrupts the result.
- One goal failing should not sink the unrelated half of the run.
- You need an audit record of what ran, where, and at what cost.
- The work should run on Copilot cloud agents rather than the user's machine.

Do **not** reach for it when you have a single goal (use `phoenix-goal`) or when what you need is a
*proof of completion* rather than execution (use `phoenix-intent`). They compose — see below.

## How to call it

One MCP call, `phoenix_mission`:

```json
{
  "capacity": 2,
  "backend": "local",
  "goals": [
    {"id": "build",       "depends_on": [],                    "task": "cargo build"},
    {"id": "unit",        "depends_on": ["build"],             "task": "cargo test --lib"},
    {"id": "integration", "depends_on": ["build"],             "task": "cargo test --test api"},
    {"id": "package",     "depends_on": ["unit","integration"],"task": "cargo package"}
  ]
}
```

- `task` is an **argv string**, split on whitespace, run with no shell. Pipes, `&&`, globs, and
  redirection do not work. Call a script if you need them.
- Goals may be declared in any order — the planner topologically sorts them.
- `capacity` defaults to 2. `backend` defaults to `"local"`.
- `workspace` (optional) is resolved under `PHOENIX_WORKSPACE`; it defaults to `.phoenix-mission`.

The response is a set of independently checkable facts, not a summary judgement:

```json
{
  "ok": true, "settled": true, "goals_total": 4,
  "goals_succeeded": 4, "goals_failed": 0,
  "peak_concurrency": 2, "isolation_ok": true, "chains_ok": true,
  "ledger": {"entries": 4, "unreadable": 0, "total_cost_micros": 0},
  "goals": [{"goal": "build", "outcome": "succeeded", "had_lease": true, "had_worktree": true}]
}
```

`ok` is a conjunction: everything settled **and** nothing failed **and** every trace chain verified
**and** every executed goal held both a lease and a worktree **and** the mission budget survived.
Read the individual fields when it is `false` — they say which clause broke.

## Running on GitHub Copilot cloud agents

Set `"backend": "cloud"` and each goal is submitted to the Copilot Agent Tasks API and polled to a
terminal state. Requires in the environment:

| Variable | Required | Meaning |
|---|---|---|
| `GITHUB_TOKEN` | yes | Token authorized for Copilot agent tasks on the repo |
| `GITHUB_REPOSITORY` | yes | `owner/repo` |
| `GITHUB_API_URL` | no | Defaults to `https://api.github.com` |

A cloud goal reports the branch it produced, plus whatever model and usage the remote disclosed. A
field the remote did not report stays `null` all the way into the ledger — **"we were not told" must
never be rendered as "it was free."** If the tool returns `cloud backend setup failed`, the
environment is missing; say so instead of silently falling back to local.

## Refusals — returned as values, never panics

The mission runtime panics on a malformed graph, so the plan is validated first and bad input comes
back as `{"ok": false, "error": ...}`:

| Refusal | Cause |
|---|---|
| `no goals supplied` | Empty `goals` |
| `capacity must be at least 1` | `capacity: 0` can never admit anything |
| `duplicate goal id "x"` | Two goals share an id |
| `goal "x" depends on itself` | Self-edge |
| `goal "x" depends on unknown goal "y"` | Typo or missing goal |
| `goal "x" has an empty task` | Nothing to run |
| `dependency cycle among goals [...]` | The graph is not a DAG |

Fix the input and call again. Never "work around" a refusal by deleting the edge that produced it —
that edge was load-bearing or it would not have been declared.

## Composing with the rest of Phoenix

```
phoenix-intent   decomposes an intent into N goals + PROVES the composite (phoenix_intent_accept)
      │
      └── phoenix-mission   SCHEDULES those goals: order, isolation, ledger, cloud
                │
                └── each goal's task is the thing phoenix-goal / phoenix-ralph would have run
```

`phoenix-mission` answers *"did the work run, in the right order, isolated, and recorded?"*
It does **not** answer *"is the goal objectively done?"* — that is `phoenix_accept`, failure-first,
and it is not optional. A green mission over a vacuous gate is still not done.

So the honest full shape for a multi-goal task is:

1. `phoenix-intent` — decompose, write the manifest, baseline every check **RED**.
2. `phoenix-mission` — execute the DAG.
3. `phoenix_intent_accept` — prove all N goals went red→green on their own intact traces.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "capacity: 8 will make this 8× faster." | Only if you have 8 independent goals. Dependencies serialize; the DAG shape sets the ceiling, not `capacity`. |
| "The mission returned ok, so the goals are done." | `ok` means it *ran and was recorded*. Done is `phoenix_accept`, failure-first. |
| "I'll skip depends_on, the order looks fine." | Goals now run **concurrently**. Without `depends_on` they will genuinely collide. |
| "Record order shows what ran first." | Records are joined in admission order, not completion order. Read the ledger for timing. |
| "The remote reported no cost, so it was free." | It reported nothing. `null` is not `0`. |
| "I'll use a shell pipe in task." | `task` is argv, no shell. Put it in a script. |

## Red Flags — stop

- Goals share mutable state outside their worktrees. Concurrency makes that a real race, not a
  theoretical one — declare `depends_on` or make them independent.
- A refusal came back and you are editing the DAG to silence it rather than to fix it.
- `chains_ok` is false → a trace chain is broken; the audit record cannot be trusted. Investigate.
- `isolation_ok` is false → a goal executed without a lease or worktree. Do not accept the run.
- You are reporting the mission as DONE without a `phoenix_accept` / `phoenix_intent_accept` proof.
