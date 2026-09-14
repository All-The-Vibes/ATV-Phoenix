# Orchestration Reference

This reference defines the state machine, lane selection matrix, route history rules, and
repair logic for the `/showoff` skill. The orchestrator in `SKILL.md` reads this before
selecting or launching any worker lanes.

Core rule: worker lanes are read-only researchers that RETURN structured findings. They
never write shared files or private scratch paths. The orchestrator is the only writer of
`evidence-dossier.md`, `showoff-plan.md`, and every later artifact.

## State Labels

After running `scripts/validate-output.mjs` against the most recent output directory, map
its `state` field to one of these labels:

| Label | Meaning | Next route |
|-------|---------|------------|
| `cold` | No output directory or no artifacts | `inspect` |
| `has-evidence` | `evidence-dossier.md` present and nonempty | `plan` |
| `has-plan` | `showoff-plan.md` present with all required sections | `compose` |
| `composing` | `composition-brief.md` and the `composition\` project exist | `compose` (continue) |
| `rendered` | `showoff.mp4` present and nonzero | `finish` |
| `has-poster` | `showoff.jpg` present and nonzero | `finish` (continue) |
| `done` | All mechanically verifiable gates pass, including a valid manifest | `deliver` |
| `broken` | Errors reported by validator | `repair` |

These labels are the single source of truth. `SKILL.md`, `docs/architecture.md`,
`scripts/project-context.mjs`, and `scripts/validate-output.mjs` all use this exact set.

## Routes

| Route | Trigger | Action |
|-------|---------|--------|
| `inspect` | State is `cold` | Launch all 5 lanes in parallel; reconcile; write dossier and plan |
| `plan` | State is `has-evidence` | Launch `product-narrator`, `visual-curator`, `proof-auditor`, `taste-director`; reconcile; write plan |
| `compose` | State is `has-plan` or `composing` | Gate 3 self-review, media checkpoint, write brief, HyperFrames handoff, check, preview approval, render |
| `finish` | State is `rendered` or `has-poster` | Bake poster (gate 7), write share copy (gate 8), write manifest (gate 9) |
| `deliver` | State is `done` | Report output paths to the user; stop |
| `repair` | State is `broken` | Apply targeted fixes; re-sense; increment repair counter |

## Route History

Maintain a `routeHistory` list in working memory for the duration of the run. Push the
current state label onto this list each time the state is sensed. Re-sense from disk after
every gate.

Stop and surface an error if EITHER of:
- The same state label appears at positions `[n]` and `[n-1]` (consecutive repeat =
  oscillation): a repair was applied but the state did not change.
- `repairCount >= 3`: the maximum number of repair attempts (3) has been reached.

Do not loop back further than one step. If a repair moves the state backward more than one
gate, that is a structural error; report it and stop rather than attempting a multi-gate
rewind.

## Oscillation Examples

The following sequences should trigger an immediate stop:

```
["cold", "cold"]                          <- inspect produced nothing
["has-plan", "broken", "has-plan"]        <- repair did not fix the plan
["composing", "broken", "composing"]      <- composition error not resolved
```

Report the route history and the last validator error list when stopping early.

## Lane Selection Matrix

Select lanes based on which sections are absent or stale. When cold, all five are selected.
On resume, select only the lanes needed for the missing or stale sections.

| Lane | Section it informs | Select when |
|------|--------------------|-------------|
| `evidence-investigator` | facts for `evidence-dossier.md` | Dossier missing or empty |
| `product-narrator` | `## Narrative` in the plan | Section absent or plan does not exist |
| `visual-curator` | `## Visual Assets` in the plan | Section absent or plan does not exist |
| `proof-auditor` | `## Proof Audit` in the plan | Section absent or plan does not exist |
| `taste-director` | `## Taste` in the plan | Section absent or plan does not exist |

When state is `cold`, all five lanes are selected. When resuming from `has-evidence`, the
`evidence-investigator` is deselected and the other four are selected.

When the host supports subagents, launch all selected lanes for a phase in one parallel
batch. Do not serialize them. When the host has no subagent primitive, execute the selected
lanes inline in the orchestrator, batching independent reads and searches where possible
and keeping each lane's findings logically separate. Missing subagents must not stop the
workflow. No lane depends on another lane's output.

## Parallel Launch Protocol

Launch selected lanes as one host-native subagent batch when that capability exists. Each
lane receives:

1. Its lane name and role description (from SKILL.md).
2. The source: the project root path, PR URL, or app URL (Windows path on Windows).
3. The parsed flags from the `/showoff` invocation text (tone, format, duration, audience,
   goal, media, narration, title).
4. The guard rails (no fabrication, UNVERIFIED exclusion, no publishing).
5. The instruction to RETURN findings only and to write nothing.

No lane is told the results of any other lane. Each lane reads the source directly and
returns a structured findings block. The orchestrator collects all returns before writing.

## Reconciliation and Write Protocol

After all selected lanes return, the orchestrator:

1. Cross-checks the narrator's and auditor's claims against the investigator's facts and
   the source itself. Only mechanically verifiable claims are kept.
2. Drops or downgrades every `UNVERIFIED` claim so it never reaches the screen or narration.
3. Resolves conflicting findings by re-reading the cited source and synthesizing one
   canonical version per section (for example, keep a pacing note in `## Taste` and a
   story note in `## Narrative`).
4. Writes `evidence-dossier.md`, then `showoff-plan.md`, then (later) the brief and the
   remaining artifacts. The orchestrator is the only writer.

## Repair Protocol

When state is `broken`, identify the specific failing gate from the validator output and
apply the minimum targeted fix:

| Failing gate | Repair action |
|-------------|---------------|
| Gate 1 (evidence) | Re-run `evidence-investigator` with broader glob patterns; rewrite the dossier |
| Gate 2 (plan) | Re-run any lane whose section is missing; rewrite that section of the plan |
| Gate 3 (review) | Fix the specific checklist item that failed |
| Gate 4 (brief/handoff) | Rewrite `composition-brief.md`; re-create the `composition\` project |
| Gate 5 (check) | Apply HyperFrames lint fixes; re-run `npx hyperframes check` |
| Gate 6 (render) | Re-run preview approval and render; check FFmpeg availability |
| Gate 7 (poster) | Re-select frame 0, re-run check/render, re-extract `showoff.jpg` |
| Gate 8 (share copy) | Write `share-copy.md` from the plan summary |
| Gate 9 (manifest) | Write or repair `showoff-manifest.json` |

After applying a repair, increment `repairCount` and re-sense from disk. If
`repairCount >= 3`, stop. The maximum is 3 everywhere.

## Timestamps

All timestamps in directory names and `showoff-manifest.json` use the format
`YYYYMMDD-HHMMSS` in local time. Collect the timestamp once at skill start and reuse it
throughout the run so all artifacts in one run share the same timestamp.

## Preserving Prior Runs and Resume Semantics

Never delete or overwrite a prior completed (`done`) run directory. Read prior runs for
context, but apply the following rules when the positional argument is an existing run
directory:

| Run state | User intent | Action |
|-----------|-------------|--------|
| State is NOT `done` (incomplete) | User asks to resume, repair, or finish | Continue writing into the **same** directory. Add or repair only missing or stale artifacts; validated artifacts are not deleted or rewritten. |
| State is `done` (completed) | Any invocation | Treat as source material only. Create a new timestamped sibling directory under `showoff-output\`. Never write into the completed run. |

A normal invocation (positional is a project root, PR URL, or app URL, not a prior run
directory) always creates a new timestamped directory. The resume path is triggered only
when the positional argument is explicitly an existing run directory AND the user plainly
asks to resume/repair/finish it.
