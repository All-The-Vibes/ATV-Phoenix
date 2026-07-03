---
type: Phoenix Skill
name: phoenix-intent
description: Decompose a high-level vague intent into N concrete /goal instances (≤5), each with its own phoenix_sense acceptance check, proven complete via composite phoenix_accept (all N saw_red AND green_after_red AND currently_green). Use when a task is multi-faceted (build + integrate + configure + notify) with independent or sequentially-dependent sub-goals. Use when the user says /intent, /phoenix-intent, "decompose this", "parallel goals", or gives a multi-outcome intent. For a single goal use phoenix-goal instead.
license: MIT
---

# phoenix-intent — decompose → N verified goals → composite proof

phoenix-goal handles **one goal with one acceptance check**. Many real tasks are multi-faceted
— *"build the connector, integrate it, configure the scheduler, and notify the team"* — with
parallel independent sub-goals and sequential dependencies. `phoenix-intent` is the orchestration
layer:

> **decompose → validate all RED → execute (parallel where independent) → prove composite done**

The composite acceptance gate is satisfied **only** when all N goals are individually proven
failure-first: each saw_red AND green_after_red AND currently_green on its own intact trace.
No shortcut. No self-report.

## The flow

```
vague intent  ("build and ship the feature, notify the team")
   │
   ▼  FRAME + confirm  ── restate intent, decompose into N goals (≤5), invite correction
   │
   ▼  FORMALIZE each goal  ── one phoenix_sense acceptance check per goal (must start RED)
   │                           write .phoenix-intent/intent.json
   │
   ▼  BASELINE  ── run `phoenix-mcp sense` for EACH goal check (per-goal PHOENIX_WORKSPACE)
   │              ALL must be RED — any green check is vacuous, re-target it
   │
   ▼  EXECUTE  ── per-goal phoenix-ralph loop (PHOENIX_WORKSPACE=.phoenix-intent/<goal_id>)
   │              parallel where depends_on=[], sequential where dependencies exist
   │
   ▼  COMPOSITE PROOF  ── `phoenix-mcp intent-accept .phoenix-intent/intent.json`
                           ok=true only when ALL goals saw_red + green_after_red + green_now
```

## The manifest (`intent.json`)

```json
{
  "intent": "wire the Teams notification into the daily pipeline and verify end-to-end",
  "goals": [
    {
      "id": "build-connector",
      "title": "Build the Teams connector module",
      "kind": "build",
      "check": { "kind": "command_exit", "target": ["cargo", "test", "--", "teams"], "expect": 0 },
      "depends_on": []
    },
    {
      "id": "configure-webhook",
      "title": "Wire the webhook endpoint into the pipeline config",
      "kind": "configure",
      "check": { "kind": "regex_in_file", "target": ["config/pipeline.toml"], "expect": "teams_webhook" },
      "depends_on": ["build-connector"]
    },
    {
      "id": "notify-team",
      "title": "Send a test Teams notification and confirm receipt",
      "kind": "notify",
      "check": { "kind": "command_exit", "target": ["node", "scripts/verify-teams.mjs"], "expect": 0 },
      "depends_on": ["configure-webhook"]
    }
  ]
}
```

**Manifest rules:**
- `id`: stable kebab-case; becomes the per-goal trace directory name (`.phoenix-intent/<id>`).
- `kind`: optional — `build`, `integrate`, `configure`, `notify`, `cron`, `webhook`.
  Used to select the right typed acceptance-check template.
- `depends_on`: empty array = independent (can run in parallel).
  Non-empty = this goal waits for listed goals to be proven before starting.
- Max 5 goals per intent. More than 5 is a signal to decompose into multiple intents.

## Per-goal traces (isolation)

Each goal has its **own** tamper-evident trace at:

```
.phoenix-intent/<goal_id>/.phoenix/trace.jsonl
```

When running a per-goal ralph loop set `PHOENIX_WORKSPACE` to the goal's workspace:

```powershell
$env:PHOENIX_WORKSPACE = "$repo\.phoenix-intent\build-connector"
phoenix-mcp sense '@.phoenix-intent/build-connector/done-check.json'
```

The composite accept (`phoenix-mcp intent-accept`) reads ALL per-goal traces and rejects the
composite unless every single goal trace shows failure-first satisfaction.

## Steps

1. **FRAME the run.** Restate the intent in one sentence. Name the N goals you'll formalize.
   List which are independent and which are dependent. Invite correction before any edit.

2. **FORMALIZE each goal** (the non-skippable part). For each goal:
   - Run `phoenix-think` or interview until the acceptance check is unambiguous.
   - Write the check into the intent manifest. The check MUST fail today (start RED).
   - *If you can't write a check that fails today, the goal is still too vague.*
   Write the complete manifest to `.phoenix-intent/intent.json`.

3. **BASELINE all checks.** Run `phoenix-mcp sense` for every goal (with per-goal workspace).
   Every check must be RED. Any green check is a vacuous gate — re-target it.

4. **EXECUTE per-goal.** For each goal (in dependency order):
   - Set up `.phoenix-intent/<id>/` with a `done-check.json`, `PROMPT.md`, and `backlog.json`.
   - Run `phoenix-ralph` with `PHOENIX_WORKSPACE=<repo>/.phoenix-intent/<id>`.
   - Independent goals (empty `depends_on`) may run in parallel.

5. **COMPOSITE PROOF.** Call `phoenix-mcp intent-accept .phoenix-intent/intent.json`.
   ok=true only when ALL goals are proven. Attach the result as evidence.

6. **REPORT.** Write `.phoenix-intent/completed.json` with the composite accept result,
   goal traces, and git tag.

## Automation goal types and typed templates

Use `dist/intent/automation-templates/` to select the right acceptance-check template:

| `kind`        | Acceptance-check pattern                              | Template                         |
|---------------|------------------------------------------------------|----------------------------------|
| `build`       | `command_exit` (tests / cargo build)                 | _(use existing done-check patterns)_ |
| `integrate`   | `command_exit` (integration test or smoke test)      | _(use existing done-check patterns)_ |
| `configure`   | `regex_in_file` (config key present)                 | _(use existing done-check patterns)_ |
| `notify`      | `command_exit` (verify notification script)          | `automation-templates/teams-notification.json` |
| `cron`        | `command_exit` (verify scheduled task registered)    | `automation-templates/cron-beat.json`          |
| `webhook`     | `command_exit` (verify webhook endpoint reachable)   | `automation-templates/webhook-trigger.json`    |

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll skip the baseline RED check." | A check never seen failing proves nothing — it's a vacuous gate. |
| "5 goals is too few." | If you need more than 5, decompose into two intents and compose them. The ceiling prevents unbounded blast radius. |
| "I'll use one shared trace for all goals." | Shared traces allow one goal's events to satisfy another's gate. Per-goal isolation is the feature. |
| "The goals are independent so I'll skip `depends_on`." | Great — leave `depends_on: []`. But still prove each independently. |
| "The composite says ok so I'm done." | Only if it's `ok=true`. A composite accept must show `goals_ok == goal_count`. |

## Red Flags — stop

- Any goal's check is green at baseline → re-target it (vacuous gate).
- Goal count > 5 → split the intent.
- You wrote `depends_on` that creates a cycle → fix the DAG.
- The composite accept is `ok=false` → one or more goals are not proven; loop does not stop.
- You weakened a goal's check to make it pass → re-scope, re-baseline, re-prove.

## Relationship to the other skills

`phoenix-intent` = **DECOMPOSE N goals + COMPOSITE PROOF**, delegating each goal's loop to
**phoenix-ralph** (via **phoenix-goal** for FORMALIZE). It composes the per-goal ralph loops
and proves the composite done signal. Think of it as:

```
phoenix-intent
  └─ goal-1 → phoenix-goal → phoenix-ralph (PHOENIX_WORKSPACE=.phoenix-intent/goal-1)
  └─ goal-2 → phoenix-goal → phoenix-ralph (PHOENIX_WORKSPACE=.phoenix-intent/goal-2)
  └─ ...
  └─ composite proof: phoenix-mcp intent-accept
```
