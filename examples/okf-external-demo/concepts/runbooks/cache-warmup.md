---
type: Runbook
title: Cache warm-up
description: Pre-warm the edge cache after a cold start so the origin is not stampeded.
tags: [cache, performance, cold-start]
owner: platform-oncall
---

# Cache warm-up

After a full cache flush or region cold start, warm the edge before sending live traffic so the
origin does not take a thundering-herd load.

## Procedure

1. Pull the top 500 keys from the [customer-events](/concepts/datasets/customer-events.md) dataset.
2. Run `acmectl cache warm --keys top500.txt --concurrency 16`.
3. Confirm edge hit-rate is above 90% before shifting traffic.

## See also

- [incident-rollback](/concepts/runbooks/incident-rollback.md) — cache is often flushed during a rollback.
