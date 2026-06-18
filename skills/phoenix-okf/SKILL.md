---
name: phoenix-okf
type: Phoenix Skill
description: Produce, validate, and consume Open Knowledge Format (OKF v0.1) bundles — turn Phoenix's code graph (graph.json) into browsable, diffable markdown knowledge, make the skill pack an OKF bundle, and ingest any external OKF bundle as token-cheap progressively-disclosed context. Use when the user says /phoenix-okf, "export the graph", "make an OKF bundle", "knowledge bundle", or wants portable, inspectable knowledge instead of an opaque graph.json.
license: MIT
---

# phoenix-okf — knowledge that pays rent in the open

## Overview
[OKF (Open Knowledge Format)](references/OKF-SPEC-0.1.md) is a vendor-neutral spec for
representing knowledge as a directory of markdown files with YAML frontmatter — one required key
(`type`), graph-shaped via plain markdown links, with `index.md` for progressive disclosure. It
is the format Phoenix's Context Assembly pillar already implies: *pay once to understand
structure, then never again.* This skill makes that knowledge **portable and inspectable**
instead of trapped in an opaque `.token-master/graph.json`.

> A bundle is a directory. If you can `cat` a file you can read it; if you can `git clone` it you can ship it.

## When to use
- You have a graphed repo (`.token-master/graph.json`) and want the knowledge **human-readable,
  diffable, and consumable by any tool** (Obsidian, the OKF graph viewer, another agent).
- You want skill discovery to ride a **standard** progressive-disclosure format.
- You want to feed an **external** OKF bundle (a data catalog, runbooks, org knowledge) into a
  Phoenix run as cheap context.

**When NOT to use:** a single local lookup grep answers in one turn. OKF earns its place on
*reusable, shareable* knowledge, not one-off questions.

## Three moves

### 1. Produce — code graph → OKF bundle
```
python scripts/okf_export.py --graph .token-master/graph.json --out okf-out --name <repo>
```
One concept document per source file; cross-file edges become bundle-relative markdown links.
INFERRED (name-matched, ~0.8-confidence) edges are flagged `candidate` — **verify at the cited
`file:line` before trusting one for a risky change** (phoenix-context honesty rule). Auto-writes
per-directory `index.md`, a root `index.md` (declaring `okf_version`), and a `log.md`.

### 2. Validate — the objective gate
```
python scripts/okf_validate.py okf-out
```
Checks OKF §9 conformance: every non-reserved `.md` has parseable frontmatter and a non-empty
`type`; reserved files (`index.md`/`log.md`) follow their rules. Exit 0 = conformant — use it as
a `phoenix_sense` check. Broken cross-links are tolerated per spec (warning, not error) unless
`--strict-links`.

### 3. Consume — ingest an OKF bundle as cheap context
```
python scripts/okf_ingest.py <bundle> [--query TYPE_OR_TAG] [--full PATH] [--max N]
```
Index-first by default: emits the bundle's progressive-disclosure outline (types, tags, concept
list) without dumping every document — the cheapest sufficient context. `--query` filters by
`type` or tag; `--full` prints one concept's body. Tolerates broken links and unknown types.

### Bonus — make the skill pack itself an OKF bundle
```
python scripts/okf_skillsync.py skills
```
Adds `type: Phoenix Skill` to each `SKILL.md` (idempotent, non-breaking) and generates
`skills/index.md`, so the capability library and knowledge share one progressive-disclosure roof.

## Why this elevates Phoenix
- **Context Assembly, now inspectable.** The strongest measured pillar (TokenMasterX) stops
  hiding in JSON; its knowledge becomes a git-reviewable artifact.
- **Reuse standards, don't reinvent.** Adopts a vendor-neutral spec instead of a bespoke schema.
- **Harness → platform.** Producing *and* consuming OKF turns a code harness into a knowledge
  platform that carries and grows knowledge across runs.

## Red Flags
- Dumping a whole bundle into context. → `okf_ingest` index-first, then `--full` only what matters.
- Trusting a `candidate` edge for a refactor. → Verify at `file:line`, or escalate to the AST backend.
- Hand-editing the generated bundle. → It is derived; re-run `okf_export` and let git diff it.

## Citations
[1] [Open Knowledge Format SPEC v0.1](references/OKF-SPEC-0.1.md) — local mirror of
GoogleCloudPlatform/knowledge-catalog/okf/SPEC.md.
