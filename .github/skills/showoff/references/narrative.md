# Narrative Reference

This reference defines the hook formula, beat arc, timing rules, and style guidance used
by the `product-narrator` lane (which returns findings only) and the orchestrator's gate 3
story review. The orchestrator, not the lane, writes `showoff-plan.md`.

## Hook Formula

The hook is the single sentence that opens the video. It must:

1. Name the concrete user benefit (what the user can now do or avoid).
2. Be free of vague adjectives ("powerful", "seamless", "amazing", "next-gen").
3. Be specific enough that someone who has never seen the project understands it.
4. Be sourced -- the claim must appear in `evidence-dossier.md`.

Formula: `[Audience] can now [action] without [friction] -- using [project name].`

Acceptable variants:
- `[Project name] lets [audience] [action] in [timeframe].`
- `[Project name] replaces [old approach] with [new approach] for [audience].`

Reject any hook that contains: "revolutionary", "game-changing", "world-class",
"state-of-the-art", "best-in-class", "unique", "disrupting", or similar superlatives.
If the evidence dossier does not support a strong hook, write a weaker factual one
rather than fabricating a stronger one.

## 3-Beat Arc

Every showoff video follows a 3-beat arc:

| Beat | Name | Content | Duration fraction |
|------|------|---------|-------------------|
| 1 | Problem | The pain or gap the project addresses | 0.25 of total |
| 2 | Solution | What the project does (the mechanism) | 0.45 of total |
| 3 | Proof | Evidence the solution works (demo, metric, screenshot) | 0.30 of total |

These fractions are the default. Adjust when:
- No clear problem is stated in the evidence: allocate 0.10 to beat 1, 0.60 to beat 2.
- Multiple strong proof items exist: shift up to 0.10 from beat 2 to beat 3.

## Beat Timing

Given `--duration` (default 25 s), compute beat seconds as:

```
beat1_secs = round(duration * 0.25)
beat2_secs = round(duration * 0.45)
beat3_secs = duration - beat1_secs - beat2_secs   (remainder)
```

Example for 25 s: beat1 = 6 s, beat2 = 11 s, beat3 = 8 s.
Example for 40 s: beat1 = 10 s, beat2 = 18 s, beat3 = 12 s.
Example for 15 s: beat1 = 4 s, beat2 = 7 s, beat3 = 4 s.

## Style by Audience

| Audience | Language register | Proof emphasis |
|----------|------------------|----------------|
| `devs` | Technical, specific (name the tech, the API, the pattern) | Code snippets, CLI output, diff |
| `execs` | Outcome-first, no jargon | Metrics, time/cost savings, screenshots |
| `general` | Plain language, analogy if helpful | Demo recording, before/after |
| custom phrase | Match register to the phrase | Best available proof type |

## Style by Goal

| Goal | Opening | Proof beat emphasis |
|------|---------|-------------------|
| `demo` | Lead with the working product | Screen recording > screenshot |
| `pitch` | Lead with the problem (pain) | Metric or user quote |
| `update` | Lead with what changed | Diff / commit / changelog entry |
| `tutorial` | Lead with the outcome (what you will be able to do) | Step-by-step screenshot sequence |

## Tone Vocabulary

| Tone | Word choice | Sentence length | Energy |
|------|-------------|----------------|--------|
| `casual` | Conversational, contractions OK | Short | Warm |
| `professional` | Precise, no contractions | Medium | Confident |
| `bold` | Active verbs, imperative mood, minimal adjectives | Short | High |

## On-Screen Text Rules

Every text element in the composition must:
- Come verbatim from `evidence-dossier.md` or be a reformulation of a sourced fact.
- Have its source path noted as a comment in `showoff-plan.md`.
- Fit within the frame at the chosen format (landscape/vertical/square) at the
  HyperFrames base resolution (1920x1080, 1080x1920, or 1080x1080).
- Be readable within the allotted beat duration (minimum 2 s of hold time per card).

## Narration Script (when --narration is set)

The narration script is a linear sequence of cues:

```markdown
## Narration Script

[beat1 0s-Xs] <spoken text for beat 1>
  source: evidence-dossier.md#<section>

[beat2 Xs-Ys] <spoken text for beat 2>
  source: evidence-dossier.md#<section>

[beat3 Ys-Zs] <spoken text for beat 3>
  source: evidence-dossier.md#<section>
```

Narration text must not repeat on-screen text verbatim; it should complement it.
Reading pace: approximately 130-150 words per minute for `professional` tone,
150-170 words per minute for `bold`, and 120-140 for `casual`.

Word count per beat = (beat_secs / 60) * words_per_minute.

## Share Copy (gate 8)

`share-copy.md` holds platform-ready copy variants. The exact section layout is defined
once in [delivery.md](delivery.md) (LinkedIn default, plus Twitter/X and YouTube when the
destination calls for them). Every block is sourced from the project identity and the hook
in the evidence dossier. Do not add links, hashtags, or handles unless they appear in the
project evidence, and do not include any claim that is not verifiable from the evidence
inventory.
