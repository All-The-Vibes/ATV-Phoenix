# Composition Brief

## Routing
workflow:
flow: automation

## Project
subject:
source:

## Story
message:
angle:
audience:

## Format
destination:
aspect:
duration:

## Visual language
design_read:
DESIGN_VARIANCE:
MOTION_INTENSITY:
VISUAL_DENSITY:
type_system:
radius_system:
accent:

## Evidence
<!--
List every real asset to be used, in scene order.
Format: - <description> -- <type: capture | screenshot | recording | export | photo>
Do not list placeholder or fake UI here. If a slot has no asset yet, mark it
as MISSING and block render until it is filled.
-->

## Media
narration: off
music: off
media_approved: false
media_disabled: false

## Acceptance gates
<!--
Confirm each gate before signing off on the composition plan.
-->
- [ ] All on-screen text passes WCAG AA contrast check
- [ ] No fake or fabricated UI in any frame
- [ ] Preflight rubric in delivery.md passes with zero BLOCKER failures
- [ ] npx hyperframes check passes with zero errors
- [ ] Preview approved before final render

---
<!--
INSTRUCTIONS FOR THE CALLER

1. Load the hyperframes skill before filling this brief:
      npx hyperframes skills update <workflow>
   where <workflow> is one of:
      product-launch-video  (source is a website or web app)
      pr-to-video           (source is a GitHub PR)
      general-video         (all other cases)

2. Read the matched route file from the installed HyperFrames skill:
      references/routes/<workflow>.md
   Answer any must-have fields the route requires that are not already
   covered here.

3. Load domain skills as needed per the HyperFrames SKILL.md table.
   - /hyperframes-core  -- composition structure, timing
   - /hyperframes-animation  -- motion rules
   - /hyperframes-creative  -- design specs
   - /hyperframes-cli  -- check, preview, render
   - Media OS  -- all media assets

4. Do not re-ask questions this brief already answers. Fields filled here
   are locked. Missing fields are marked explicitly; ask only for those.

5. Pre-render gate (mandatory):
      npx hyperframes check
   Do not render if this fails.

6. Preview before final render:
      npx hyperframes preview

7. After render, ShowOff produces:
      showoff.mp4
      showoff.jpg      (best settled frame)
      showoff-plan.md
      composition-brief.md  (this file, post-filled)
      share-copy.md
      showoff-manifest.json
   Plus captions.vtt and transcript.md only when narration is on.

DESIGN SYSTEM QUICK REFERENCE

DESIGN_VARIANCE >= 5: no centered-template layouts. Layout must earn every
axis. Asymmetric or editorial composition required.

MOTION_INTENSITY: every animation needs a stated reason (reveals info,
confirms state change, guides attention, establishes pace). Animate only
transform and opacity. No layout animation.

MOTION_INTENSITY >= 5: queue a reduced-motion render variant (cuts-only).

VISUAL_DENSITY >= 7: spatial hierarchy must carry the read; label every
information layer.

No pure black (#000000) or pure white (#FFFFFF).
No default purple gradients or neon glow.
No filler verbs (empower, transform, unlock, leverage, supercharge).
One typeface family. One radius system. One accent color.
WCAG AA contrast on all text overlays.
-->
