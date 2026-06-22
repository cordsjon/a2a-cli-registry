from core.models import Cli, Capability, CliEdge
from core.planner.search import plan_chain, Chain


def _fleet(db):
    for slug, intag, ins, outs, se, conf in [
        ("pdf2text", "convert", "file:pdf", "text:doc", "none", "declared"),
        ("summarize", "summarize", "text:doc", "text:summary", "none", "declared"),
        ("shred", "delete", "text:doc", "text:summary", "destructive", "declared"),
    ]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags=intag, input_types=ins,
                          output_types=outs, side_effect=se, confidence=conf))
    db.add(CliEdge(from_slug="pdf2text", to_slug="summarize", via_type="text:doc"))
    db.add(CliEdge(from_slug="pdf2text", to_slug="shred", via_type="text:doc"))
    db.commit()


def test_known_goal_yields_expected_chain(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    assert chains[0].slugs == ["pdf2text", "summarize"]   # exact expected, ranked first


def test_unsatisfiable_goal_returns_empty(db):
    _fleet(db)
    assert plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["audio:wav"]) == []


def test_destructive_excluded_by_default(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    assert all("shred" not in c.slugs for c in chains)    # destructive hop excluded


def test_destructive_included_when_allowed(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"],
                        allow_side_effects=["destructive"])
    assert any("shred" in c.slugs for c in chains)


def test_ranking_keys_are_independently_ordered(db):
    """Two equal-length chains where key-2 (side-effect count) and key-3
    (min-confidence) DISAGREE. A has fewer side-effects but lower confidence;
    B has more side-effects but higher confidence. A MUST rank first — proving
    side-effect-count strictly precedes min-confidence."""
    # chain A: clean but inferred ; chain B: writes-fs but declared
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    for slug, se, conf in [("A", "none", "inferred"), ("B", "writes-fs", "declared")]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags="g", input_types="text:x",
                          output_types="text:goal", side_effect=se, confidence=conf))
        db.add(CliEdge(from_slug="src", to_slug=slug, via_type="text:x"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        allow_side_effects=["writes-fs"])
    # A (fewer side-effects) ranks before B (more side-effects), despite lower confidence
    assert chains[0].slugs[-1] == "A"


def test_chain_hops_carry_routing_fields(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    assert chains, "expected at least one chain"
    chain = chains[0]
    assert chain.slugs == ["pdf2text", "summarize"]
    # every hop must have side_effect and provenance
    for hop in chain.hops:
        assert "side_effect" in hop, f"missing side_effect in hop: {hop}"
        assert "provenance" in hop, f"missing provenance in hop: {hop}"
    # second hop (index 1) must carry the routing edge fields
    hop1 = chain.hops[1]
    assert hop1["from"] == "pdf2text", f"expected from=pdf2text, got {hop1.get('from')}"
    assert hop1["to"] == "summarize", f"expected to=summarize, got {hop1.get('to')}"
    assert "via_type" in hop1, f"missing via_type in second hop: {hop1}"
    assert hop1["via_type"] == "text:doc"


def _inferred_fleet(db, se="writes-fs"):
    """Only path file:pdf -> text:goal passes through 'mid', which carries an
    INFERRED side_effect. Used to prove inferred-side-effect exclusion."""
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    db.add(Cli(slug="mid", lang="python"))
    db.add(Capability(cli_slug="mid", intent_tags="g", input_types="text:x",
                      output_types="text:goal", side_effect=se, confidence="inferred"))
    db.add(CliEdge(from_slug="src", to_slug="mid", via_type="text:x"))
    db.commit()


def test_inferred_side_effect_excluded_by_default(db):
    # the ONLY path to text:goal goes through an inferred writes-fs hop -> excluded
    _inferred_fleet(db, se="writes-fs")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert all("mid" not in c.slugs for c in chains)
    assert chains == []   # no alternative path exists


def test_inferred_side_effect_included_when_allowed(db):
    # same goal, operator opts into writes-fs blast-radius class -> chain returned
    _inferred_fleet(db, se="writes-fs")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        allow_side_effects=["writes-fs"])
    assert any("mid" in c.slugs for c in chains)


def test_inferred_network_side_effect_excluded_by_default(db):
    # network inferred side-effect is also excluded by default
    _inferred_fleet(db, se="network")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert chains == []


def test_inferred_none_side_effect_still_allowed(db):
    # inferred confidence with NO blast radius (none) is harmless -> NOT excluded
    _inferred_fleet(db, se="none")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert any("mid" in c.slugs for c in chains)


def test_declared_writes_fs_still_allowed_by_default(db):
    # a DECLARED writes-fs hop must STILL be included by default (only INFERRED
    # writes-fs/network is newly excluded)
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    db.add(Cli(slug="dmid", lang="python"))
    db.add(Capability(cli_slug="dmid", intent_tags="g", input_types="text:x",
                      output_types="text:goal", side_effect="writes-fs", confidence="declared"))
    db.add(CliEdge(from_slug="src", to_slug="dmid", via_type="text:x"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert any("dmid" in c.slugs for c in chains)


def test_terminates_on_cyclic_typegraph(db):
    db.add(Cli(slug="a", lang="python")); db.add(Cli(slug="b", lang="python"))
    db.add(Capability(cli_slug="a", input_types="t", output_types="t", intent_tags="x",
                      side_effect="none", confidence="declared"))
    db.add(Capability(cli_slug="b", input_types="t", output_types="t", intent_tags="x",
                      side_effect="none", confidence="declared"))
    db.add(CliEdge(from_slug="a", to_slug="b", via_type="t"))
    db.add(CliEdge(from_slug="b", to_slug="a", via_type="t"))
    db.commit()
    # must terminate (cycle guard), not hang
    plan_chain(db, goal_inputs=["t"], goal_outputs=["nonexistent"], max_chain_depth=4)
