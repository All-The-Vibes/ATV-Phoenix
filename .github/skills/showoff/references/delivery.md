# ShowOff -- Delivery Contract Reference

## Output files

Every ShowOff run writes these files into its timestamped run directory
`showoff-output\<YYYYMMDD-HHMMSS>\`. No output file is optional unless marked.

| File                   | Description                                            | When produced       |
| ---------------------- | ------------------------------------------------------ | ------------------- |
| evidence-dossier.md    | Reconciled, sourced facts about the project            | Always              |
| showoff-plan.md        | Narrative, assets, proof audit, taste, scene breakdown | Always              |
| composition-brief.md   | The brief handed to HyperFrames (post-fill copy)       | Always              |
| composition\           | HyperFrames project directory                          | Always              |
| showoff.mp4            | Final rendered video                                   | Always              |
| showoff.jpg            | Strongest settled frame, baked as frame 0 of the video | Always              |
| share-copy.md          | Platform-ready copy variants for distribution          | Always              |
| showoff-manifest.json  | Provenance, reproducibility, and asset metadata        | Always              |
| captions.vtt           | WebVTT captions file                                   | Only if narration   |
| transcript.md          | Plain-text transcript                                  | Only if narration   |

Do not produce captions or transcript when narration is off. Never overwrite a prior
timestamped run directory.

---

## showoff.jpg -- poster from verified frame 0

The poster is a real frame of the rendered composition, not a post-hoc thumbnail. The flow:

1. Review the settled candidate snapshots from the composition.
2. Select the strongest (title fully visible, no mid-transition state, no motion blur,
   representative of the content).
3. Set that visual as frame 0 of the composition.
4. Re-run `npx hyperframes check` and re-render so frame 0 is verified.
5. Extract showoff.jpg from the verified frame 0:

```
ffmpeg -i showoff.mp4 -vframes 1 -q:v 2 showoff.jpg
```

**A later settled frame is never acceptable.** Do not use `-ss` to seek to a later
timestamp (for example `-ss 3.5`); that extracts a frame after frame 0 and will fail the
pixel-match gate. If frame 0 is not fully settled -- for example it shows a dim
pre-animation state -- you must modify the composition's initial state so the first
rendered frame is already fully settled, then re-render and re-extract from the new
frame 0. There is no shortcut: re-composition and re-render are required.

`validate-output.mjs` enforces this automatically: when both `showoff.mp4` and
`showoff.jpg` are present it decodes frame 0 of the video and the poster's single frame
to raw rgb24 (via `ffmpeg`, no shell), requires equal nonzero buffer lengths (dimensions
must match), and rejects the run if the mean absolute error across all byte values exceeds
the documented threshold of 3.0.

Do not claim ffmpeg can embed a thumbnail into an already-rendered MP4 without
re-composition. The poster must correspond to the actual frame 0 of showoff.mp4.

---

## showoff-plan.md -- required sections

The plan structure is defined by `templates/showoff-plan.md`. The orchestrator (not a
worker lane) writes it. Required `##` sections:

- `## Config` -- the parsed flags and source
- `## Narrative` -- hook and 3-beat arc (from product-narrator findings)
- `## Visual Assets` -- scored table of real on-disk files (from visual-curator findings)
- `## Proof Audit` -- claim / source / PASS|UNVERIFIED inventory (from proof-auditor)
- `## Taste` -- design read, dials, color, typography, pacing, opening motion
- `## Scene Breakdown` -- scene / duration / content / evidence source table
- `## Media Opportunities` -- what was offered, approved, and skipped in the media pass
- `## Preflight Result` -- the preflight rubric table with PASS/FAIL for every item
- `## Narration Script` -- present only when `--narration` is set
- `## Gate 3 Review` -- the self-review checklist

Gate 2 (validated by `scripts/validate-output.mjs`) requires at minimum the four
lane-produced sections: Narrative, Visual Assets, Proof Audit, Taste.

---

## share-copy.md -- required sections

Produce copy variants for each destination named in the brief. At minimum:

```markdown
# Share Copy

## LinkedIn (recommended default)
**Headline:**
**Body (1200 chars max):**
**Hashtags (max 5):**

## Twitter / X (optional, include when requested)
**Tweet (280 chars):**

## YouTube description (when destination includes YouTube)
**Title:**
**Description:**
**Tags:**
```

No filler verbs. No generic SaaS copy. Every claim in the copy must be verifiable from the
evidence inventory. Do not add links, hashtags, or handles unless they appear in the
project evidence.

---

## showoff-manifest.json -- required fields

One comprehensive manifest schema. The orchestrator writes it at gate 9.

```json
{
  "schema_version": "1",
  "showoff_version": "0.1.0",
  "produced_at": "<ISO 8601 timestamp>",
  "project": {
    "subject": "",
    "source": "",
    "route": ""
  },
  "config": {
    "tone": "",
    "format": "",
    "duration_s": 25,
    "audience": "",
    "goal": "",
    "title": ""
  },
  "dials": {
    "DESIGN_VARIANCE": 5,
    "MOTION_INTENSITY": 5,
    "VISUAL_DENSITY": 5
  },
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
  "gates": {
    "evidence": "pass",
    "plan": "pass",
    "review": "pass",
    "handoff": "pass",
    "check": "pass",
    "preview": "pass",
    "render": "pass",
    "poster": "pass",
    "share-copy": "pass",
    "narration": "pass",
    "manifest": "pass"
  },
  "reproducibility": {
    "hyperframes_version": "",
    "brief_hash": "",
    "evidence_sources": []
  },
  "media_assets": [],
  "claims": [],
  "external_services_used": [],
  "published": false
}
```

Field notes:
- `showoff_version`: always `0.1.0` (the skill version).
- `config`: the resolved invocation flags (after defaults, clamping, and last-wins).
- `gates`: a map of gate name to `pass` for every gate that actually passed. Do not list a
  gate as passed unless its artifact is present and valid.
- `reproducibility.hyperframes_version`: output of `npx hyperframes --version` at render
  time.
- `reproducibility.brief_hash`: SHA-256 of composition-brief.md at render time (use
  `Get-FileHash composition-brief.md -Algorithm SHA256` on Windows).
- `reproducibility.evidence_sources`: list of `{ path, type, captured_at }` for every
  project asset used in the composition.
- `media_assets`: provenance for every asset resolved through Media OS (see media.md).
- `claims`: every factual claim on screen or in narration:
  `{ "claim": "<text>", "source": "<URL or document>", "verified": true }`.
- `external_services_used`: every external endpoint actually contacted this run (the PR or
  app URL host, and any approved Media OS provider). Empty when nothing external was
  contacted.
- `published`: always `false`. ShowOff never automatically publishes or uploads the
  finished artifacts.

Do not add an always-local flag. It would misrepresent the boundary: ShowOff may contact
the supplied PR/URL host, the active agent host, HyperFrames skill updates, and approved Media OS
providers. State the precise boundary instead (see the boundary section below).

---

## Preflight rubric

Run this rubric manually before every render. Each item is a binary check. Mark PASS or
FAIL. Any FAIL at the BLOCKER level stops the render.

### BLOCKERS -- render is halted if any fails

```
[ ] B1  All evidence is from the real project (no fake UI, no placeholder div-built screens)
[ ] B2  No unsourced factual claims in on-screen text or narration script
[ ] B3  All text overlays pass WCAG AA contrast (4.5:1 body, 3:1 large text)
[ ] B4  No pure black (#000000) or pure white (#FFFFFF) in the composition
[ ] B5  No default purple gradient backgrounds in any scene
[ ] B6  No neon glow / bloom on text elements
[ ] B7  No generic SaaS filler copy on screen (empower/transform/unlock/leverage)
[ ] B8  npx hyperframes check returns zero errors
[ ] B9  Preview approved by caller before this render was initiated
[ ] B10 If narration is on: captions.vtt and transcript.md are ready to ship
[ ] B11 If MOTION_INTENSITY >= 5: a reduced-motion variant (cuts-only) is produced
```

B11 is a blocker only when MOTION_INTENSITY >= 5, matching the mandatory reduced-motion
rule in taste.md. Below 5 it does not apply.

### WARNINGS -- flag in plan but do not block render

```
[ ] W1  DESIGN_VARIANCE >= 5 and no centered layouts present (confirm layout was intentional)
[ ] W2  All animated properties are transform or opacity only (no layout animation)
[ ] W3  Music / grade was approved (not silently added)
[ ] W4  Any stock imagery is disclosed in the manifest with license status
[ ] W5  Any unverified license field in media_assets is flagged for review
[ ] W6  Inaccessible custom cursors are not visible in any screen capture segment
[ ] W7  share-copy.md contains no claims not found in the evidence inventory
```

### HOW TO RUN

There is no automated script for the full preflight rubric. Walk through each item manually
against the composition. Paste the result table (with PASS/FAIL) into the
`## Preflight Result` section of showoff-plan.md.

The pre-render gate `npx hyperframes check` (item B8) is automated and its output should be
included verbatim. Preview approval (B9) must be obtained before the final render call.

---

## Platform variants (on-request only)

When the caller requests a platform variant after the primary render:

1. Identify the required aspect and max duration from the platform spec.
2. Update composition-brief.md with `variant_destination` and re-run via HyperFrames.
3. Name the variant `showoff-<platform>.mp4` (for example showoff-instagram.mp4).
4. Update showoff-manifest.json to list the variant under outputs.
5. Do not re-run the full evidence or story pipeline for variants; only reframe and trim
   from the primary composition.

Supported variant targets (when requested): instagram (1:1, 60s), tiktok (9:16, 60s),
shorts (9:16, 60s), linkedin-post (1:1, 30s), twitter (16:9, 140s).

---

## Delivery boundary

ShowOff never automatically publishes or uploads the finished video, poster, or any
artifact. It writes only to the timestamped run directory and sets `published: false`.
External network access is limited and explicit: ShowOff may contact the supplied PR or
app URL, the active agent host, the HyperFrames sub-skill, and explicitly approved Media
OS providers. Media providers receive only approved request payloads; credential files are
never read. Every external endpoint actually contacted is recorded in
`external_services_used`. Any publish action is the caller's responsibility and is out of
scope for this skill.
