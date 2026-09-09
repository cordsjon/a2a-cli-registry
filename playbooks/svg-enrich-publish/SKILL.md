---
name: svg-enrich-publish
description: RETIRED SEED — never ran; none of its three CLIs exist. Kept as the worked example of a broken-drift playbook
tags: [seed, example, retired, svg, etsy]
allowed-tools: [svg-enrich, care-card, etsy-export]
status: retired
---

## Why this is here

The seed playbook from the Playbook Launchpad backend plan
(`docs/superpowers/plans/2026-06-27-playbook-launchpad-backend.md`), written to
prove the loader and drift check work end-to-end. It did that job.

**It was never runnable.** `svg-enrich`, `care-card` and `etsy-export` are not
in the registry and not on PATH — they were illustrative names, not real CLIs.
Verified 2026-09-09 against `~/.hermes/cli-registry.db`:

    drift = {"status": "broken", "missing_clis":
             ["svg-enrich", "care-card", "etsy-export"]}

That `broken` status is the drift check working correctly, not a defect.

## Why it was not rewritten

The pipeline it describes cannot be assembled from CLIs that exist. Of the
three stages, only "care card" has a healthy implementation
(`render_care_cards_cli`); `etsy_publish_cli` is unhealthy
(`ModuleNotFoundError: No module named 'app'`), and no SVG-enrichment CLI is
registered at all. Rewriting it against those slugs would publish a pipeline
that still cannot run — a fabricated green.

## Why it was not deleted

It is the only worked example of a playbook whose CLIs went missing. The unit
tests cover `broken` drift with synthetic fixtures (`test_signature.py` uses a
CLI named `ghost`), so this file adds no test coverage — its value is as
documentation of the failure mode against real registry data.

`status: retired` marks it. Note that `list_playbooks` does not filter on
status, so it is still served; a client wanting to hide retired entries should
filter on this field.

## Steps

1. svg-enrich  in: {raw: raw}      out: EnrichedSvg
2. care-card   in: {doc: s1/out}   out: CareCards
3. etsy-export in: {cards: s2/out} out: Listing
