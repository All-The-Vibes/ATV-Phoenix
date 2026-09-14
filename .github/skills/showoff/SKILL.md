---
name: showoff
description: >
  Turn a project, GitHub PR, app URL, or evidence path into a polished showcase video,
  poster, sourced plan, HyperFrames composition brief, manifest, and share copy. Use when
  asked to show off a project, make a demo video or showcase reel, turn a PR into a video,
  create a product demo, or produce a shareable clip. Runs inline with host-native tools in
  GitHub Copilot CLI, VS Code Copilot agent mode, or Claude Code; subagents are optional.
  Never automatically publishes or uploads finished artifacts.
argument-hint: >
  [--tone <phrase>] [--format landscape|vertical|square] [--duration <10-90>]
  [--audience <phrase>] [--goal demo|pitch|update|tutorial] [--narration]
  [--media auto|approved|none] [--title "My Project"] [<path-or-URL>]
disable-model-invocation: true
compatibility: >
  GitHub Copilot CLI, VS Code Copilot agent mode, and Claude Code. Requires Node.js,
  HyperFrames through npx, and FFmpeg for final poster verification.
---

# showoff

Turn a project, a GitHub PR URL, a URL-backed app, or a supplied evidence path into a
polished showcase video with a poster and share copy. You are the orchestrator. Worker
lanes are read-only researchers that return findings to you. You are the only writer of
shared artifacts.

## Execution mode

Run the orchestrator inline in the main conversation so the media checkpoint and preview
approval can receive real user input. Do not fork the entire workflow.

Use the current host's native tools rather than assuming Claude-specific tool names:

- On GitHub Copilot CLI, use its task/subagent tool for worker lanes and its structured
  user-input tool for approvals.
- In VS Code Copilot agent mode, use available subagent and user-input tools.
- On another host, use the equivalent native primitives.
- If the host has no subagent primitive, run the selected read-only lanes inline in the
  orchestrator. Batch independent reads and searches where possible. Missing subagents are
  never a reason to stop or return only a plan.

At skill start, execute the bundled `scripts\project-context.mjs` with Node while the
target project is the working directory. Resolve the script from this skill's base
directory as exposed by the host; do not depend on a host-specific environment variable.

## Boundary (state this precisely; never overstate it)

ShowOff never automatically publishes or uploads the finished artifacts. It may contact
supplied PR/app hosts, the active agent host, HyperFrames update sources, and explicitly
approved Media OS providers. Media providers receive only the approved requests you send them;
ShowOff never reads credential files and never uploads project evidence without an
explicit approved Media OS request. Do not overstate privacy or imply the tool never
reaches the network.

Model work runs through the active host's native agent primitives. Do not call model-provider
APIs directly and do not hard-code a model name.

## Arguments

Parse the text supplied with the `/showoff` invocation directly. Do not require a
host-specific argument variable. Supported flags (double-dash) and one positional:

| Flag | Values | Default |
|------|--------|---------|
| `--tone` | any preset or freeform phrase (e.g. `casual`, `professional`, `bold`) | `professional` |
| `--format` | `landscape`, `vertical`, `square` | `landscape` |
| `--duration` | integer 10-90 (seconds) | `25` |
| `--audience` | any phrase (e.g. `devs`, `execs`, `general`) | `general` |
| `--goal` | `demo`, `pitch`, `update`, `tutorial` | `demo` |
| `--narration` | flag, no value; enables voice-over script, captions, transcript | off |
| `--media` | `auto`, `approved`, `none` | `auto` |
| `--title` | quoted string | infer from source |
| positional | path to a project root, a GitHub PR URL, or an app URL | cwd |

Unknown flags: warn and continue. Conflicting values: last one wins.
Duration outside 10-90: clamp to the nearest bound and warn.
Only the flags in the table above are accepted; warn on anything else.

**Resume semantics:** The positional argument may be an existing timestamped run directory.
- If the directory is an **incomplete** run (state is not `done`) and the user plainly asks
  to resume, repair, or finish it, continue writing into that same directory. Add or repair
  only missing or stale artifacts; do not delete or wholesale rewrite validated artifacts.
- If the directory is a **done** run, treat it as source material and create a new
  timestamped sibling directory under `showoff-output\`. Never mutate a completed run.
- There is no resume flag. The instruction is given in plain language (for example:
  "resume this run and re-render the poster").

## Platform Note

When running on Windows, use Windows-style paths with backslashes in every file path,
every shell command, and every output artifact. Do not use bash-specific syntax
(`&&`, `$()`, backtick subshells). Prefer PowerShell-safe one-liners or the Node scripts
bundled with this skill for any shell work.

## Output Layout

Create a timestamped subdirectory under the project root for every **normal** invocation:

```
<project-root>\showoff-output\<YYYYMMDD-HHMMSS>\
  evidence-dossier.md
  showoff-plan.md
  composition\               (HyperFrames project)
  showoff.mp4
  showoff.jpg
  share-copy.md
  showoff-manifest.json
  captions.vtt               (narration only)
  transcript.md              (narration only)
```

**Run vs. resume distinction:**
- **Normal invocation** (path is a project root, PR URL, or app URL): create a new
  timestamped subdirectory.
- **Incomplete run** (positional path points to an existing run directory whose state is
  not `done`, and the user asks to resume/repair/finish it): write into that same
  directory. Repair or add only missing or stale artifacts; do not delete or wholesale
  rewrite artifacts that already passed their gate.
- **Done run** (positional path points to a run directory in `done` state): treat it as
  source material only, create a new timestamped sibling under `showoff-output\`, and
  never write into the completed run.

Never overwrite or delete a completed prior run. If `showoff-output\` already exists,
read it for prior runs. Collect the timestamp once at skill start and reuse it for the
directory name and the manifest. Produce `captions.vtt` and `transcript.md` only when
`--narration` is set.

## Orchestration

See [orchestration](references/orchestration.md) for the complete state machine, lane
matrix, and route history rules. Working summary:

1. **Sense state** - run `scripts/validate-output.mjs <most-recent-output-dir>` against the
   newest existing output directory (if any). Parse its `state` field into one of: `cold`,
   `has-evidence`, `has-plan`, `composing`, `rendered`, `has-poster`, `done`, or `broken`.

2. **Select lanes** - from the selection matrix in
   [orchestration](references/orchestration.md), include only lanes whose corresponding
   section is missing or stale. When the run is cold, all five lanes are selected. On
   resume, select only the lanes needed for the missing or stale sections.

3. **Launch parallel** - when the host supports subagents, fire all selected lanes for a
   phase in one parallel batch. Otherwise execute the same lanes inline, keeping their
   findings logically separate. No lane depends on another lane's output. Each lane reads
   the source directly and returns structured findings; lanes never write shared files or
   private scratch paths.

4. **Reconcile and write** - after all selected lanes return, you (the orchestrator)
   reconcile their findings, mechanically verify every claim you intend to use, then write
   `evidence-dossier.md` and `showoff-plan.md`. You are the only writer.

5. **Gate check** - after each gate, re-sense from disk by re-running
   `validate-output.mjs`. Route forward on pass, to repair on failure, or halt on
   oscillation.

6. **Oscillation guard** - maintain a route-history list. If the same state label appears
   twice in succession, or repair attempts reach 3, stop immediately and report the last
   error list. The maximum number of repair attempts is 3 everywhere.

## Worker Lanes (read-only researchers)

Five independent lanes. Each reads the source directly and returns findings to the
orchestrator. No lane reads another lane's output, and no lane writes any file. At cold
state all five run in parallel in one batch.

### evidence-investigator

Collect raw facts only. No narrative, no opinion.

- **Project path**: read README (any capitalisation), the primary manifest
  (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, etc.), any CHANGELOG, and up
  to 5 representative source files. Record the source path for every fact.
- **PR URL**: fetch PR title, body, diff summary, and any linked issue titles.
- **App URL**: fetch page title, meta description, and visible heading text.
- Return every fact with its source path or URL. Detail rules:
  [project-inspection](references/project-inspection.md).

### product-narrator

Build story structure by reading the source directly and citing its own sources.

- Infer the hook: one sentence naming the concrete user benefit (no vague adjectives).
- Build a 3-beat arc: problem / solution / proof.
- Map beats to `--duration` using the formula in [narrative](references/narrative.md).
- Draft the narration script ONLY when `--narration` is in the invocation text.
- Return the `Narrative` findings (and narration cues if applicable) with source citations.

### visual-curator

Identify available visual evidence on disk. Never fabricate or download assets.

- Glob for images: `*.png`, `*.jpg`, `*.jpeg`, `*.gif`, `*.webp` under the project root.
- Glob for recordings: `*.mp4`, `*.mov`, `*.webm`.
- Score each file: 1 = icon/logo, 2 = screenshot, 3 = demo recording, 4 = annotated demo.
- If `--media none`, report "no external media requested" and list on-disk assets only.
- Return a scored table of real file paths for the `Visual Assets` section.

### proof-auditor

Run an independent evidence-risk and claim-verification inventory. This lane does NOT
consume another lane's dossier; it inspects the source itself.

- Enumerate every load-bearing factual claim the source could support (metrics, counts,
  capabilities) and locate the exact file and line that backs each one.
- Mark any claim with no locatable source as `UNVERIFIED`.
- `UNVERIFIED` claims must not appear on screen or in narration.
- Return a claim / source / PASS|UNVERIFIED inventory for the `Proof Audit` section.

### taste-director

Produce style guidance from the flags and a direct read of the source's visual language.

- Design read (one line), then set the three dials (see [taste](references/taste.md)):
  `DESIGN_VARIANCE`, `MOTION_INTENSITY`, `VISUAL_DENSITY`.
- Color, typography, pacing, and opening-motion direction.
- Return the `Taste` findings.

## Orchestrator reconciliation

After the lanes return, you reconcile and verify before writing anything:

- Cross-check the narrator's and auditor's claims against the investigator's facts and the
  source itself. Keep only claims you can mechanically verify.
- Drop or downgrade any `UNVERIFIED` claim so it never reaches the screen or narration.
- Resolve conflicting findings by re-reading the cited source; synthesize one canonical
  version per section.
- Write `evidence-dossier.md`, then `showoff-plan.md` from the reconciled findings, using
  [templates/showoff-plan.md](templates/showoff-plan.md) as the structure.

## Workflow Gates

Gate checks are run via `scripts/validate-output.mjs`. Full specification in
[orchestration](references/orchestration.md).

| # | Gate | Artifact | Hard blocker |
|---|------|----------|--------------|
| 1 | Evidence dossier | `evidence-dossier.md` | No sourced claims found |
| 2 | Showoff plan | `showoff-plan.md` (all required sections) | Any required section missing |
| 3 | Taste + story review | Orchestrator self-review checklist | Hook unclear or UNVERIFIED claim in plan |
| 4 | Composition brief + handoff | `composition-brief.md` and `composition\` project | Brief missing or project marker absent |
| 5 | HyperFrames check | `npx hyperframes check` exits 0 | Any error in check output |
| 6 | Preview approval + render | `showoff.mp4` exists and nonzero | Missing/zero-byte file, or preview not approved |
| 7 | Poster | `showoff.jpg` extracted from verified frame 0 | File missing, zero bytes, or pixel MAE vs frame 0 exceeds 3.0 |
| 8 | Share copy | `share-copy.md` (nonempty) | File empty |
| 9 | Manifest | `showoff-manifest.json` (required fields) | Missing required fields |

### Gate 3 - Taste/Story Review (orchestrator self-review)

Before writing the composition brief, confirm ALL of the following:
- [ ] Hook names a concrete user benefit; no vague adjectives.
- [ ] Every on-screen text claim appears in `evidence-dossier.md` with a source path.
- [ ] Total duration fits within `--duration` (clamped to 10-90 s).
- [ ] Visual Assets section lists at least one real on-disk file, OR `--media none`.
- [ ] Proof Audit has zero `UNVERIFIED` rows in any text that will be visible on screen.

Fail any check: repair the plan, re-run gate 2. Do not proceed to gate 4 until all pass.

### Gate 4 - Composition brief and HyperFrames routing

Read [composition](references/composition.md) and write `composition-brief.md` from
[templates/composition-brief.md](templates/composition-brief.md). Choose the HyperFrames
route by the source material first (not by `--goal`):

| Source material | HyperFrames route |
|-----------------|-------------------|
| GitHub PR URL or code change | `pr-to-video` |
| Website, web app, or product URL | `product-launch-video` |
| Anything else (path, footage, brief) | `general-video` |

Do not route a tutorial goal to a faceless explainer when the source is a product; the
source decides the route. Hand `--format`, `--duration`, `--tone`, and the Visual Assets
list to HyperFrames through the brief. HyperFrames owns composition mechanics, check,
preview, and render. The HyperFrames project is created under `composition\`.

**HyperFrames project scaffolding:** initialize the project directly inside `composition\`
so that marker files (`package.json`, `hyperframes.json`, `BRIEF.md`) land at
`composition\package.json` and so on. From the run directory run:

```
npx hyperframes init composition
```

or equivalently, change into the directory first and initialize the current path:

```
cd composition && npx hyperframes init .
```

Do not run `npx hyperframes init <project-name>` from inside `composition\`; that creates
a nested `composition\<project-name>\` subdirectory and copies no marker files upward.
The validator requires a recognizable marker directly in `composition\`.

### Media opportunity checkpoint (after plan, before composition)

Read [media](references/media.md). Run exactly one media-opportunity pass on the plan,
after gate 3 and before the composition brief is handed off:

- `--media none`: skip Media OS entirely; use only on-disk project assets.
- `--media approved`: skip the ask and approve the grounded opportunities the pass surfaces.
- `--media auto`: consolidate every grounded opportunity into one message and ask once.

Media OS owns asset resolution and generation, and only after explicit approval. Narration
stays off unless `--narration` is explicit; approving media does not enable narration.

### Gate 5 and 6 - Check, preview approval, render

Run `npx hyperframes check` before any render (mandatory; resolve every error first). Then
run a preview pass and obtain preview approval before the final render. HyperFrames renders
`showoff.mp4` into the run directory.

### Gate 7 - Poster selection and baking

Review the settled candidate snapshots from the composition, select the strongest (text
fully rendered, no motion blur, representative of the content), and set that visual as
frame 0 of the composition. Re-run `npx hyperframes check` and re-render so frame 0 is
verified, then extract `showoff.jpg` from the verified frame 0:

```
ffmpeg -i showoff.mp4 -vframes 1 -q:v 2 showoff.jpg
```

**A later settled frame is never acceptable.** Do not use `-ss` to seek to a later
timestamp (for example `-ss 3.5`) to extract the poster; that decodes a later frame, not
frame 0, and will fail the pixel-match check in `validate-output.mjs`. If frame 0 is not
fully settled -- for example it is a dim pre-animation state -- modify the composition's
initial state so the first rendered frame is already fully settled, then re-render and
re-extract from the new frame 0.

Do not claim that ffmpeg can embed a thumbnail into an already-rendered MP4 without
re-composition; the poster must correspond to the actual frame 0 of showoff.mp4.
`validate-output.mjs` decodes both files to raw rgb24 and rejects the run if the mean
absolute error exceeds 3.0.

### Gate 9 - Manifest

Write `showoff-manifest.json` using the single comprehensive schema in
[delivery](references/delivery.md). Required top-level keys:

```json
{
  "schema_version": "1",
  "showoff_version": "0.1.0",
  "produced_at": "<ISO-8601>",
  "project": { "subject": "", "source": "", "route": "" },
  "config": { "tone": "", "format": "", "duration_s": 25, "audience": "", "goal": "", "title": "" },
  "dials": { "DESIGN_VARIANCE": 5, "MOTION_INTENSITY": 5, "VISUAL_DENSITY": 5 },
  "design_read": "",
  "narration": false,
  "outputs": {
    "video": "showoff.mp4",
    "thumbnail": "showoff.jpg",
    "plan": "showoff-plan.md",
    "brief": "composition-brief.md",
    "share_copy": "share-copy.md",
    "captions": null,
    "transcript": null
  },
  "gates": {},
  "reproducibility": { "hyperframes_version": "", "brief_hash": "", "evidence_sources": [] },
  "media_assets": [],
  "claims": [],
  "external_services_used": [],
  "published": false
}
```

`reproducibility.hyperframes_version` is the output of `npx hyperframes --version` at render
time. `brief_hash` is the SHA-256 of `composition-brief.md`. `external_services_used` lists
every external endpoint actually contacted (PR/URL host, approved Media OS providers).
`published` is always `false`. Do not add a misleading always-local flag.

## Guard Rails (non-negotiable)

- **Never fabricate.** Do not invent metrics, testimonials, product behavior, or visual
  evidence. Every on-screen or narrated claim must appear in `evidence-dossier.md` with a
  source path.
- **Never automatically publish.** Do not call any share, upload, or publish API. ShowOff
  writes only to the run directory. It may contact the supplied PR/app host, the active
  agent host, HyperFrames, and explicitly approved Media OS providers, but it never publishes or
  uploads the finished artifacts without an explicit caller action outside this skill.
- **UNVERIFIED claims are excluded.** If proof-auditor marks a claim `UNVERIFIED`, remove
  it from the visible script, all composition text, and the narration.
- **Narration is off by default.** Generate a voice-over script, `captions.vtt`, and
  `transcript.md` only when `--narration` appears in the invocation text.
- **Source paths are retained.** Keep source-path notes in `showoff-plan.md` through all
  revisions; do not remove them for the final composition.

## References

| Reference | Content |
|-----------|---------|
| [orchestration](references/orchestration.md) | State machine, lane matrix, route history, repair cap |
| [project-inspection](references/project-inspection.md) | Evidence collection rules per source type |
| [narrative](references/narrative.md) | Hook formula, beat arc, timing, style by audience/goal |
| [taste](references/taste.md) | Design read, dials, typography, accessibility |
| [media](references/media.md) | Media OS ownership and the single media-opportunity pass |
| [composition](references/composition.md) | HyperFrames ownership, routing, brief handoff |
| [delivery](references/delivery.md) | Output contract, manifest schema, preflight rubric |
| [templates/showoff-plan.md](templates/showoff-plan.md) | Plan file structure |
| [templates/composition-brief.md](templates/composition-brief.md) | Brief handed to HyperFrames |
| `scripts/project-context.mjs` | Source state sensor (injected above) |
| `scripts/validate-output.mjs` | Output gate validator; call with the run directory path |
