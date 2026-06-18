---
type: Runbook
title: Incident rollback
description: Revert a bad production deploy to the last known-good release and confirm recovery.
tags: [incident, deploy, sev2, rollback]
owner: platform-oncall
severity: sev2
---

# Incident rollback

When a deploy degrades production, roll back before debugging. Recovery first, root cause second.

## Trigger

- Error rate above 2% for 5 minutes, or
- p99 latency above 1500 ms for 5 minutes after a release.

## Procedure

1. Identify the last green release tag from the deploy log.
2. Run `acmectl release rollback --to <tag>`.
3. Watch the [customer-events](/concepts/datasets/customer-events.md) error stream until error
   rate drops below 0.5%.
4. Post in `#incidents` and open a follow-up using the
   [ADR template rationale](/concepts/decisions/adopt-okf.md) habit: write down what happened.

## See also

- [cache-warmup](/concepts/runbooks/cache-warmup.md) — run after rollback if cache was flushed.
- Glossary: [green release](/concepts/glossary/terms.md).
