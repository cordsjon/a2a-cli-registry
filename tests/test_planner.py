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
