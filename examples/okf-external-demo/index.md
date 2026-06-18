---
okf_version: 0.1
title: Acme Platform Knowledge Catalog (external)
okf_source: acme-knowledge-catalog
---

# Acme Platform — operations knowledge bundle

A hand-authored OKF v0.1 bundle that did **not** come from Phoenix's `okf_export`. It uses a
different producer (`acme-knowledge-catalog`) and a different `type` vocabulary
(`Runbook`, `Dataset`, `Decision`, `Glossary`) to prove the Phoenix OKF tooling is vendor-neutral:
the same `okf_validate` gate and `okf_ingest` consumer read it verbatim, with zero Phoenix-specific
assumptions.

Navigate one level at a time.

# Sections

* [concepts/](concepts/) - runbooks, datasets, decisions, and glossary for the Acme platform
