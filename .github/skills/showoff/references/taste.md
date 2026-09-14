# ShowOff -- Design Taste Reference

## Core premise

A showcase video earns credibility through specificity. The moment a viewer spots
a placeholder div, a generic SaaS screenshot, or a sentence that would fit any
product, the trust signal collapses. Every visual choice must be defensible against
the question: "is this from the actual project?"

---

## Evidence hierarchy

Use assets in this order. Do not substitute a lower tier when a higher one is
available.

1. Live screen capture of the running product (highest)
2. Real screenshots of the actual UI, taken at the moment of production
3. Exported design-file frames from the project's own design source
4. Authentic terminal/editor output from real code runs
5. Diagrams built from real data or real architecture
6. Approved brand photography (credited)
7. Stock imagery only when no project asset exists and the need is purely contextual
   (lowest -- disclose in the manifest)

Never: fake div-built UI, AI-generated UI mockups, screenshot templates with dummy
content, or composited elements that imply product functionality not present.

---

## Inferred design read (one line)

Before setting dials, read the project's own visual language -- palette, radius,
type scale, spatial density -- and write one line that describes what the video
should feel like. Examples:

  "Tight grid, one accent, fast cuts -- developer utility"
  "Open air, editorial type, held frames -- brand announcement"
  "Concrete evidence, near-zero decoration -- internal tool review"

This line drives all downstream decisions. It is not a mood board.

---

## Design system dials

Three dials, each 1-10. Set them once per project from the design read. All three
interact: high variance + high density often conflicts; choose deliberately.

### DESIGN_VARIANCE (1-10)
How far the visual language diverges from a centered, grid-locked template.
- 1-3: Highly systematic, mostly symmetric, predictable
- 4-6: Asymmetric layouts allowed, editorial breaks permitted
- 7-10: Layout is expressive, hierarchy is spatial not positional

Rule: never use a centered-template layout when DESIGN_VARIANCE >= 5. At that
level the layout must earn every axis and margin.

### MOTION_INTENSITY (1-10)
How much motion is used, and how aggressive it reads.
- 1-3: Transitions only; no ambient motion; held frames dominate
- 4-6: Purposeful entrances/exits, one or two hero animations
- 7-10: Motion is a primary storytelling tool; sequences are motion-led

Rule: every animation requires a reason. Permitted reasons: reveals information,
confirms a state change, guides attention, or establishes pace. Decoration alone
is not a reason.

### VISUAL_DENSITY (1-10)
How much information is on screen at once.
- 1-3: One idea per frame, generous negative space
- 4-6: Two to three simultaneous information layers, structured
- 7-10: Dashboard-style, multiple data points visible, spatial hierarchy carries
        the read

---

## Defaults by project and audience type

| Project type                    | Audience          | DESIGN_VARIANCE | MOTION_INTENSITY | VISUAL_DENSITY |
| ------------------------------- | ----------------- | --------------- | ---------------- | -------------- |
| Developer tool / CLI            | Engineers         | 3               | 2                | 5              |
| Consumer app                    | General public    | 6               | 6                | 4              |
| Internal tool / dashboard       | Team or org       | 3               | 2                | 7              |
| Design system / component lib   | Designers + eng   | 7               | 4                | 5              |
| Open source library             | Engineers         | 4               | 3                | 5              |
| Product launch (B2B SaaS)       | Decision-makers   | 5               | 5                | 4              |
| Product launch (B2C)            | General public    | 7               | 7                | 3              |
| Code change / PR explainer      | Engineers         | 2               | 3                | 6              |
| Brand / sizzle reel             | Mixed             | 8               | 7                | 3              |

These are starting points. Adjust from the design read. Document any deviation
in showoff-plan.md.

---

## Typography rules

- One type system per video. Do not mix typeface families.
- One radius system. All rounded elements share the same radius token or a
  proportional scale thereof.
- One accent color. Derive it from the project's own palette. If the project has
  no palette, pick one neutral and one action color; justify in the manifest.
- No default purple gradients.
- No neon glow effects.
- No filler verbs in on-screen copy: "empower," "transform," "unlock," "leverage,"
  "supercharge," and synonyms are banned. Use active, concrete verbs tied to what
  the product actually does.
- No generic SaaS copy as on-screen text.
- Body/caption type must be readable at the target export resolution. Minimum
  effective size: 24px at 1080p (22px at 720p). Do not go smaller for aesthetics.
- No pure black (#000000) or pure white (#FFFFFF) anywhere in the composition.
  Use near-black and near-white to avoid crushing contrast at the extremes.

---

## Accessibility requirements

- All text overlaid on video or images: WCAG AA contrast (4.5:1 for normal text,
  3:1 for large text >= 24px or bold >= 18px). Run contrast check before render.
- No inaccessible custom cursors in any screen capture segment.
- When narration is present: provide captions and a transcript. Both are required,
  not optional. Narration is off by default.
- Reduced-motion version: any video with MOTION_INTENSITY >= 5 must have a
  reduced-motion variant that replaces transforms and fades with cuts. The
  variant is a separate render target, not a CSS media query (because the output
  is a video file, not a live page).
- Do not make unverifiable claims on screen. Every factual claim (speed, scale,
  count, rating) must be sourced. Source appears in the manifest, not necessarily
  on screen.

---

## What to animate

Animate only: `transform` (translate, scale, rotate) and `opacity`. Do not
animate font-size, border-radius, color, background-color, or layout properties
in motion sequences -- these trigger layout or paint and look cheap even when
they technically work.

For motion that serves the story (state changes, reveals, transitions): use
`transform + opacity` in combination. For ambient motion: avoid it unless the
design read specifically calls for kinetic energy (e.g., a generative art tool).

---

## No-fly list (reject immediately in preflight)

- Fake/fabricated product UI
- Default purple gradient backgrounds
- Neon glow / bloom on text
- Generic SaaS copy or filler verbs
- Inaccessible custom cursors
- Pure black or pure white elements
- Narration without captions
- Unverifiable factual claims without a source logged in the manifest
- Centered template layouts when DESIGN_VARIANCE >= 5
- Animations without a stated reason
- Layout animation (animating width, height, margin, padding, border-radius)
