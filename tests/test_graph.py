from core.models import Cli, Capability, CliEdge
from core.graph.edges import compute_edges, current_edges
from core.vocabulary import VocabularyRegistry


def _seed(db):
    db.add(Cli(slug="pdf2text", lang="python"))
    db.add(Cli(slug="summarize", lang="python"))
    db.add(Capability(cli_slug="pdf2text", input_types="file:pdf", output_types="text:doc",
                      intent_tags="convert", side_effect="none", confidence="declared"))
    db.add(Capability(cli_slug="summarize", input_types="text:doc", output_types="text:summary",
                      intent_tags="summarize", side_effect="none", confidence="declared"))
    db.commit()


def test_edge_iff_registered_type_overlap(db, clock):
    _seed(db)
    vocab = VocabularyRegistry(registered={"file:pdf", "text:doc", "text:summary"}, aliases={})
    compute_edges(db, vocab, clock)
    edges = current_edges(db)
    assert ("pdf2text", "summarize", "text:doc") in edges


def test_unverified_ports_excluded_from_edges(db, clock):
    _seed(db)
    # text:doc NOT registered -> no edge can form on it
    vocab = VocabularyRegistry(registered={"file:pdf", "text:summary"}, aliases={})
    compute_edges(db, vocab, clock)
    assert ("pdf2text", "summarize", "text:doc") not in current_edges(db)


def test_noop_recompute_emits_no_delta(db, clock):
    _seed(db)
    vocab = VocabularyRegistry(registered={"file:pdf", "text:doc", "text:summary"}, aliases={})
    compute_edges(db, vocab, clock)
    delta = compute_edges(db, vocab, clock)   # identical inputs
    assert delta == []


def test_atomic_swap_reads_complete_graph(db, clock):
    _seed(db)
    vocab = VocabularyRegistry(registered={"file:pdf", "text:doc", "text:summary"}, aliases={})
    compute_edges(db, vocab, clock)
    # a read after recompute sees the new complete set (never a partial)
    assert len(current_edges(db)) == 1


def test_hub_type_edge_requires_shared_intent_tag(db, clock):
    # bare hub type "text" shared between two CLIs that share an intent_tag → edge forms
    db.add(Cli(slug="producer", lang="python"))
    db.add(Cli(slug="consumer", lang="python"))
    db.add(Capability(cli_slug="producer", input_types="", output_types="text",
                      intent_tags="summarize", side_effect="none", confidence="declared"))
    db.add(Capability(cli_slug="consumer", input_types="text", output_types="",
                      intent_tags="summarize", side_effect="none", confidence="declared"))
    db.commit()
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    compute_edges(db, vocab, clock)
    assert ("producer", "consumer", "text") in current_edges(db)


def test_hub_type_edge_blocked_without_shared_intent_tag(db, clock):
    # bare hub type "text" shared between two CLIs with DIFFERENT intent_tags → no edge
    db.add(Cli(slug="writer", lang="python"))
    db.add(Cli(slug="reader", lang="python"))
    db.add(Capability(cli_slug="writer", input_types="", output_types="text",
                      intent_tags="generate", side_effect="none", confidence="declared"))
    db.add(Capability(cli_slug="reader", input_types="text", output_types="",
                      intent_tags="analyze", side_effect="none", confidence="declared"))
    db.commit()
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    compute_edges(db, vocab, clock)
    assert ("writer", "reader", "text") not in current_edges(db)
