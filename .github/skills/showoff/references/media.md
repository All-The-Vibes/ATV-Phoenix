# ShowOff -- Media Contract Reference

## Ownership

ShowOff does not bundle or manage media assets. All media resolution, generation, and
provenance tracking is owned entirely by Media OS. ShowOff does not reimplement Media OS
behavior. Media OS acts only after explicit approval.

---

## When to invoke Media OS

Invoke Media OS at exactly one defined moment in the ShowOff workflow: the
media-opportunity pass. This pass happens after the plan is written (gate 3 passed) and
before the composition brief is handed off. Do not invoke Media OS again unless a specific
approved asset fails to resolve and a retry with different parameters is warranted.

---

## The media-opportunity pass

Run one grounded scan of the plan. For each signal below, note the opportunity.
Consolidate all opportunities into a single ask. Ask once. Do not ask per asset. Do not add
media silently.

| Signal in the plan                                    | Opportunity to surface                              |
| ----------------------------------------------------- | --------------------------------------------------- |
| On-screen text or narration script with no voiceover  | TTS voiceover via the Media OS audio engine         |
| Any scene > ~10s with no audio bed                    | Background music (bgm) via Media OS                 |
| Hard cuts with no transition audio                    | Transition SFX via Media OS                         |
| Placeholder, upscaled, or missing contextual imagery  | Resolved image via Media OS                         |
| Emoji or styled div used as an icon                   | Real icon resolved via Media OS                     |
| Footage reading under/over-exposed or color-cast      | Corrective grade via Media OS grading               |

Default states:
- Narration: OFF. Do not add voiceover unless `--narration` is set. Approving media does
  not enable narration.
- Music: OFF by default. Offer only when a signal above is present.
- Color grade: never apply silently. Always preview before committing.

---

## Approval gate and the --media flag

The `--media` flag decides how the media-opportunity pass behaves:

- `--media auto` (default): the pass produces one consolidated message listing every
  detected opportunity with proposed defaults. The caller approves all, some, or none
  before any resolve call is made. Ask once.
- `--media approved`: skip the ask and approve the grounded opportunities the pass
  surfaces. Every resolve call is still logged.
- `--media none`: disable the entire pass. Resolve nothing beyond on-disk project assets;
  Media OS is not invoked at all.

When the composition brief carries `media_approved: true`, treat it as `--media approved`.
When it carries `media_disabled: true`, treat it as `--media none`.

---

## Resolving assets

Use the Media OS resolve entry point for every external asset:

```
node <MEDIA_DIR>\scripts\resolve.mjs --type <type> --intent "<description>" --project <dir>
```

Before resolving fresh, check candidates:

```
node <MEDIA_DIR>\scripts\resolve.mjs --type <type> --intent "<description>" --project <dir> --candidates
```

Reuse a previously resolved asset when it fits. Do not resolve duplicates.

---

## Provenance and license metadata

Every resolved asset writes a ledger record. Do not discard or override it. When
assembling `showoff-manifest.json`, include provenance fields for every media asset sourced
through Media OS:

```json
"media_assets": [
  {
    "id": "<resolve-id>",
    "type": "<type>",
    "path": "<local-path>",
    "source": "<provider or origin>",
    "license": "<license string>",
    "intent": "<what it was resolved for>"
  }
]
```

If Media OS does not return a license field for an asset, write `"license": "unverified"`
and flag it in the plan as needing review before any public distribution.

---

## Network boundary

Media OS only contacts an external provider when a resolve request has been approved
(explicitly by the caller, or by `--media approved`). Providers receive only the approved
request payload (an intent string and asset type), not project evidence, product
screenshots, or captured screens, unless the caller explicitly invokes an image-analysis
flag. Media OS never reads credential files. Every external provider actually contacted is
recorded in `external_services_used` in the manifest.

Do not claim that media resolution is entirely local. When `--media none` is set, no Media
OS provider is contacted and no external media request leaves the machine for this run.

---

## What ShowOff does not do

- Does not reimplement audio generation, TTS, music search, or grading logic
- Does not manage the media cache or the asset ledger directly
- Does not re-ask about media after the single opportunity pass is complete
- Does not add voice, music, or grades without explicit approval
- Does not modify asset license metadata
- Does not publish or upload the finished video or any asset
