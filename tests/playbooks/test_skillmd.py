from core.playbooks.skillmd import parse_skillmd, Playbook, PlaybookStep

SAMPLE = """---
name: svg-enrich-publish
description: Enrich a batch of SVGs and publish to Etsy
tags: [svg, etsy, batch]
allowed-tools: [svg-enrich, care-card, etsy-export]
status: verified
---

## Steps

1. svg-enrich  in: {raw: raw}      out: EnrichedSvg
2. care-card   in: {doc: s1/out}   out: CareCards
3. etsy-export in: {cards: s2/out} out: Listing
"""


def test_parses_frontmatter_and_steps():
    pb = parse_skillmd(SAMPLE, slug="svg-enrich-publish")
    assert isinstance(pb, Playbook)
    assert pb.slug == "svg-enrich-publish"
    assert pb.description.startswith("Enrich a batch")
    assert pb.tags == ("svg", "etsy", "batch")
    assert pb.allowed_tools == ("svg-enrich", "care-card", "etsy-export")
    assert pb.status == "verified"
    assert len(pb.steps) == 3
    assert pb.steps[0] == PlaybookStep(id="s1", cli="svg-enrich", inputs={"raw": "raw"}, out_type="EnrichedSvg")
    assert pb.steps[1].inputs == {"doc": "s1/out"}


def test_missing_frontmatter_raises():
    import pytest
    with pytest.raises(ValueError, match="frontmatter"):
        parse_skillmd("no frontmatter here", slug="x")
