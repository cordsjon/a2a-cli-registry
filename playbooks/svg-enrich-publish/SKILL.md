---
name: svg-enrich-publish
description: Enrich a batch of SVGs and publish to Etsy
tags: [svg, etsy, batch, enrich, publish]
allowed-tools: [svg-enrich, care-card, etsy-export]
status: draft
---

## Steps

1. svg-enrich  in: {raw: raw}      out: EnrichedSvg
2. care-card   in: {doc: s1/out}   out: CareCards
3. etsy-export in: {cards: s2/out} out: Listing
