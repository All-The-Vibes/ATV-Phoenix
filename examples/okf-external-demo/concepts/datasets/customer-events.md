---
type: Dataset
title: Customer events
description: Append-only event stream of customer interactions, partitioned by day.
tags: [events, streaming, pii]
owner: data-platform
classification: confidential
retention_days: 400
---

# Customer events

An append-only stream of customer interaction events (page views, clicks, purchases), partitioned
by UTC day and keyed by `customer_id`.

## Schema

| Field | Type | Notes |
|-------|------|-------|
| `event_id` | uuid | primary key |
| `customer_id` | string | foreign key, hashed |
| `kind` | enum | `view` \| `click` \| `purchase` |
| `ts` | timestamp | event time, UTC |
| `payload` | json | kind-specific body |

## Consumers

- [incident-rollback](/concepts/runbooks/incident-rollback.md) reads the error stream from here.
- [cache-warmup](/concepts/runbooks/cache-warmup.md) derives the top-500 hot keys from here.
