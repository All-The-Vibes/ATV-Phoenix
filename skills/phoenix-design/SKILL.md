---
name: phoenix-design
description: Design-engineering craft for interfaces that feel right — the animation decision framework (should it animate at all, what's the purpose, what curve), the invisible details that compound, and a required Before/After review table. Gated where possible by objective checks (lint, build, visual/interaction verification). Grounded in Emil Kowalski's design-engineering philosophy. Use when building or reviewing UI, animations, or interactions, or when the user says /phoenix-design, "make it feel better", or "review this UI".
license: MIT
---

# phoenix-design — taste is the differentiator, polished with evidence

> Encodes [Emil Kowalski's](https://animations.dev) design-engineering philosophy: in a world where
> everyone's software is good enough, **taste is the differentiator**, and unseen details compound into
> interfaces people love without knowing why. Phoenix adds the verify-heal discipline so polish ships
> without regressing build/lint/behavior.

## Core philosophy
- **Taste is trained, not innate.** Reverse-engineer great interfaces; understand *why* they feel right.
- **Unseen details compound.** Users rarely notice them consciously — that's the point. The aggregate of
  invisible correctness is what makes software feel stunning.
- **Beauty is leverage.** People pick tools on the whole experience. Good defaults + good motion stand out.

## The Animation Decision Framework (answer in order, before writing any animation)

### 1. Should this animate at all?
| Frequency | Decision |
|---|---|
| 100+×/day (keyboard shortcuts, command palette) | **No animation. Ever.** |
| Tens of ×/day (hover, list nav) | Remove or drastically reduce |
| Occasional (modals, drawers, toasts) | Standard animation |
| Rare/first-time (onboarding, celebration) | Can add delight |

**Never animate keyboard-initiated actions** — they repeat hundreds of times a day; animation makes them
feel slow. (Raycast has no open/close animation. That's optimal for something used constantly.)

### 2. What is the purpose?
Every animation needs a clear answer to "why does this animate?" Valid: spatial consistency, state
indication, explanation, feedback. No purpose → no animation.

### 3. What curve & properties?
- Animate **specific properties** (`transform`, `opacity`) — never `all` (janky, animates the unexpected).
- **`ease-out`** for things entering / responding to user action (instant feedback). `ease-in` feels
  sluggish for UI. Custom curves for personality.
- **Nothing appears from nothing:** enter with `scale(0.95)` + `opacity`, not `scale(0)`.
- **Respond to press:** interactive elements get an `:active` state (`transform: scale(0.97)`).
- **Scale from origin:** popovers/dropdowns scale from their trigger (`transform-origin`), modals stay centered.
- Honor `prefers-reduced-motion`.

## Review Format (REQUIRED)
When reviewing UI code you MUST output a single markdown table — never a "Before:/After:" list:

| Before | After | Why |
| --- | --- | --- |
| `transition: all 300ms` | `transition: transform 200ms ease-out` | Specify exact properties; avoid `all` |
| `transform: scale(0)` | `transform: scale(0.95); opacity: 0` | Nothing in the real world appears from nothing |
| `ease-in` on dropdown | `ease-out` with a custom curve | `ease-in` feels sluggish; `ease-out` is instant feedback |
| No `:active` on button | `transform: scale(0.97)` on `:active` | Buttons must feel responsive to press |
| `transform-origin: center` on popover | `var(--radix-popover-content-transform-origin)` | Popovers scale from their trigger |

## Verify the polish (the Phoenix part — taste, but gated)
Craft is not an excuse to skip evidence. Where a check exists, gate on it:
- **Build/lint stay green:** `phoenix_sense {"kind":"command_exit","target":["npm","run","lint"],"expect":0}`
  and the build — beautiful code that doesn't compile isn't shipped.
- **Behavior unbroken:** if the component has tests, sense them; a motion tweak must not break logic.
- **Reduced-motion path exists:** check (regex or test) that `prefers-reduced-motion` is honored.
- **Visual/interaction check when possible:** screenshot or interaction test for the changed state.
- Snapshot before a risky restyle so `phoenix_heal` can roll back a regression.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "More animation = more delight." | High-frequency animation feels *slow*. Delight lives in rare moments; everyday actions want speed. |
| "`transition: all` is convenient." | It animates properties you didn't intend (layout, color) and janks. Name the exact property. |
| "`ease-in` looks fine." | For UI entrances it feels laggy. `ease-out` gives the instant feedback users read as responsive. |
| "It's just a style change, no need to check." | Style changes break builds, lint, and reduced-motion paths. Sense them; taste still needs evidence. |
| "I'll write the review as a Before/After list." | The required format is a markdown table. Lists bury the reasoning; the table makes each call legible. |

## Red Flags
- Animation on a keyboard-repeated action. → Remove it; speed beats motion there.
- `transition: all` or `scale(0)` entrances. → Name properties; enter from `0.95`+opacity.
- No `:active` / no `prefers-reduced-motion`. → Add both; responsiveness and accessibility are table stakes.
- A UI review written as a prose list. → Use the Before/After table.
- Shipping a restyle without a green build/lint sense. → Gate it; beauty that breaks the build isn't shipped.

## Next
Pair with `phoenix-build` (implement under the heal loop), `phoenix-typescript` (typed components), and
`phoenix-review`/`phoenix-ship` (gate the polish on green evidence). Deeper craft: Emil's course at
[animations.dev](https://animations.dev).
