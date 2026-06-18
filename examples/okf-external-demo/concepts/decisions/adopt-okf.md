---
type: Decision
title: Adopt OKF v0.1 for the knowledge catalog
description: ADR — standardize Acme's operational knowledge on the Open Knowledge Format.
tags: [adr, knowledge, standards]
status: accepted
date: 2026-06-17
---

# ADR: Adopt OKF v0.1 for the knowledge catalog

## Context

Acme's runbooks, dataset docs, and decisions lived in three different tools with three different
export formats. None were diffable in git, and no agent could read all three.

## Decision

Standardize on **OKF v0.1**: every knowledge asset is a markdown file with YAML frontmatter whose
only required key is `type`. The catalog is a plain directory, navigable via `index.md` files.

## Consequences

- Any OKF-aware consumer (including external ones like Phoenix's `okf_ingest`) can read the catalog
  with no Acme-specific code.
- Knowledge is git-reviewable and tool-agnostic.
- See the [glossary](/concepts/glossary/terms.md) for shared terms used across concepts.
