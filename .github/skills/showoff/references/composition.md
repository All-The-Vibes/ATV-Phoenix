# ShowOff -- Composition Contract Reference

## Ownership split

ShowOff owns:
- Evidence selection (which real captures, screenshots, or recordings to use)
- Story shape (the narrative arc, scene order, pacing intent)
- Tone (design read, dial settings, visual language description)
- Visual language (type system, radius system, accent, color rules)
- Format (aspect ratio, target resolution, platform destination)
- Duration (target length and hard cap)
- Source moments (which specific frames or clips carry which story beats)
- Acceptance gates (what "done" looks like for this specific project)

HyperFrames owns:
- Composition mechanics (HTML structure, data-* timing attributes, track layout)
- Seek-safe timing (frame accuracy, runtime state, deterministic playback)
- Runtime (the animation engine, playback loop, render pipeline)
- Checks (lint, validate, snapshot diff, pre-render gates)
- Render (the actual frame export and MP4 encode)

ShowOff instructs HyperFrames through the composition brief (`composition-brief.md`)
handoff. ShowOff does not reimplement any HyperFrames behavior. ShowOff does not write
composition HTML directly unless acting as a companion in /general-video mode.

---

## HyperFrames route selection

Choose the route based on the project's primary source material. Apply the
first match.

| Source material                            | HyperFrames route         |
| ------------------------------------------ | ------------------------- |
| Website URL, web app, or product site      | product-launch-video      |
| GitHub PR reference or code change         | pr-to-video               |
| Anything else (scripts, footage, briefs)   | general-video             |

These routes are defined in the HyperFrames skill at:
  references/routes/product-launch-video.md
  references/routes/pr-to-video.md
  references/routes/general-video.md

Never attempt to reconstruct route behavior from memory. Always load the
relevant route file from the installed HyperFrames skill.

---

## Skill loading instructions for the caller

Before executing any ShowOff composition, the caller must:

1. Load the hyperframes skill:
   ```
   npx hyperframes skills update <route-name>
   ```
   Use the bare name without slash: product-launch-video, pr-to-video,
   or general-video.

2. Read the matched route file in full from the installed skill.

3. Load domain skills on demand per the HyperFrames SKILL.md table:
   - /hyperframes-core for composition structure and timing
   - /hyperframes-animation for motion rules and transitions
   - /hyperframes-creative for design specs and typography
   - /hyperframes-cli for check, preview, render
   - Media OS for all media assets

Do not re-read this file to answer "what does this route require?" --
read the composition brief and the route file. This file describes the handoff
shape, not the execution.

---

## HyperFrames project scaffolding

The HyperFrames project must be initialized directly inside `composition\` so that marker
files (`package.json`, `hyperframes.json`, `BRIEF.md`) land at the canonical paths
`composition\package.json`, `composition\hyperframes.json`, etc.

From the run directory, run:

```
npx hyperframes init composition
```

Or change into the directory and initialize the current path:

```
cd composition && npx hyperframes init .
```

Do not run `npx hyperframes init <project-name>` from inside `composition\`; that creates
a nested `composition\<project-name>\` subdirectory and places all marker files there
instead of directly under `composition\`. Do not manually copy marker files upward from a
nested subdirectory. `validate-output.mjs` requires a recognizable marker (`package.json`
or `BRIEF.md`) directly in `composition\` and will report a partial gate if the marker is
absent or nested.

---

## Composition brief handoff format

ShowOff produces `composition-brief.md` before any HyperFrames workflow executes. The
brief is the single artifact the workflow reads. It prevents redundant interview questions
by supplying all ShowOff-owned fields up front. The HyperFrames project is created under
`composition\` and reads this brief.

Minimum required fields in every composition brief:

```markdown
# BRIEF

## Routing
workflow: <product-launch-video | pr-to-video | general-video>
flow: automation

## Project
subject: <one-line description of what is being shown>
source: <URL, PR reference, or "footage/brief">

## Story
message: <one sentence -- what the viewer should remember>
angle: <the specific framing -- changelog / launch / feature-reveal / tour / etc>
audience: <primary audience in plain terms>

## Format
destination: <platform and orientation -- e.g. YouTube 16:9, LinkedIn 1:1>
aspect: <16:9 | 1:1 | 9:16>
duration: <target in seconds, e.g. 45s; hard cap e.g. 90s max>

## Visual language
design_read: <the one-line design read from taste.md>
DESIGN_VARIANCE: <1-10>
MOTION_INTENSITY: <1-10>
VISUAL_DENSITY: <1-10>
type_system: <typeface family or token name>
radius_system: <token name or px value>
accent: <hex value with brief justification>

## Evidence
<!-- List actual assets in order of use -->
- <asset description> -- <type: capture | screenshot | recording | export>

## Media
narration: <on | off>
music: <off | approved | <bgm-resolve-id>>
media_approved: <true | false>
media_disabled: <false | true>

## Acceptance gates
<!-- What "done" looks like for this project -->
- All on-screen text passes WCAG AA contrast check
- No fake UI in any frame
- Preflight rubric passes with zero blockers
- npx hyperframes check passes
- Preview approved before final render
```

Fields ShowOff does not own (HyperFrames fills these from its workflow):
- storyboard: yes/no (ask the caller if not explicit)
- Composition HTML structure
- Timing attributes
- Render settings (fps, codec, output path)

---

## Pre-render gate

Before any render command, run:

```
npx hyperframes check
```

This is mandatory. Do not proceed to render if check fails. Report the
failure and resolve it before continuing.

---

## Preview and snapshot

Before final render, run a preview pass:

```
npx hyperframes preview
```

or for a snapshot at a specific timestamp:

```
npx hyperframes snapshot --at <timestamp>
```

Preview approval from the caller is required before the final render call.
This applies to automation and companion modes alike.

---

## Final render expectations

The HyperFrames render produces showoff.mp4 in the run directory. After render
completes, ShowOff is responsible for:
- Selecting the strongest settled frame from the composition, setting it as frame 0,
  re-running `npx hyperframes check` and re-rendering so frame 0 is verified, then
  extracting showoff.jpg from that verified frame 0 (see delivery.md)
- Assembling showoff-manifest.json with provenance and reproducibility fields
- Writing showoff-plan.md from the composition plan
- Writing share-copy.md with platform-ready copy variants

HyperFrames does not produce these files. ShowOff produces them after render.

---

## Acceptance gates (mechanical)

These are the minimum checks ShowOff confirms before closing out a project.
Each check has a boolean result. A "no" on any blocker-level check stops delivery.

See delivery.md for the full preflight rubric.
