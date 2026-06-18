---
type: Glossary
title: Platform glossary
description: Shared vocabulary referenced across Acme runbooks, datasets, and decisions.
tags: [glossary, vocabulary]
---

# Platform glossary

- **Green release** — the most recent release tag that passed all health checks in production.
- **Cold start** — a region or cache brought up from empty, with no warm state.
- **Thundering herd** — many clients hitting the origin simultaneously after a cache miss/flush.
- **Hot key** — a cache key in the top percentile of request volume.

Used by [incident-rollback](/concepts/runbooks/incident-rollback.md) and
[cache-warmup](/concepts/runbooks/cache-warmup.md).
