import pytest
from core.populate import populate, MassRemovalBreaker
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord
from core.adapters.python_adapter import PythonAdapter
from core.vocabulary import VocabularyRegistry
from core.models import Cli, Capability
from sqlmodel import select


class FakeSource:
    def __init__(self, recs): self._recs = recs
    def discover(self): return self._recs


def _rec(slug, ins, outs):
    return CliRecord(slug=slug, lang="python", path="/x", bucket=None, project=None,
                     description="", source_class="t", source_run_id="r",
                     declared_capability=CapabilityRecord(
                         intent_tags=["convert"], input_types=ins, output_types=outs,
                         side_effect="none", confidence="declared"))


def test_not_standalone_flag_persists_to_cli_row(db, clock):
    """US-CLIAUDIT-83: a CliRecord.not_standalone=True must land on the Cli row
    so the prober (and UI) can preserve it."""
    rec = _rec("subapp_cli", ["text"], ["text"])
    rec.not_standalone = True
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)
    row = db.get(Cli, "subapp_cli")
    assert row.not_standalone is True


def test_populate_upserts_and_builds_edges(db, clock):
    src = FakeSource([_rec("pdf2text", ["file:pdf"], ["text:doc"]),
                      _rec("summarize", ["text:doc"], ["text:summary"])])
    vocab = VocabularyRegistry(registered={"file:pdf", "text:doc", "text:summary"}, aliases={})
    result = populate(db, src, [PythonAdapter()], vocab, clock)
    assert result["added"] == 2
    assert db.exec(select(Cli)).all().__len__() == 2
    assert ("pdf2text", "summarize", "text:doc") in set(map(tuple, [(d[0], d[1], d[2]) for d in result["edge_delta"]]))


def test_mass_removal_trips_breaker(db, clock):
    vocab = VocabularyRegistry(registered={"file:pdf", "text:doc"}, aliases={})
    populate(db, FakeSource([_rec("a", ["file:pdf"], ["text:doc"]),
                             _rec("b", ["file:pdf"], ["text:doc"])]), [PythonAdapter()], vocab, clock)
    # now a source that removes both (100% > 30%) must trip the breaker
    with pytest.raises(MassRemovalBreaker):
        populate(db, FakeSource([]), [PythonAdapter()], vocab, clock)


def test_removed_cli_leaves_no_orphan_capabilities(db, clock):
    # Start with 4 CLIs so removing 1 = 25% < 30% threshold; breaker does NOT trip.
    vocab = VocabularyRegistry(
        registered={"file:pdf", "text:doc", "text:summary", "text:report"},
        aliases={},
    )
    initial_recs = [
        _rec("pdf2text",  ["file:pdf"],      ["text:doc"]),
        _rec("summarize", ["text:doc"],      ["text:summary"]),
        _rec("reporter",  ["text:summary"],  ["text:report"]),
        _rec("doomed",    ["file:pdf"],      ["text:doc"]),
    ]
    populate(db, FakeSource(initial_recs), [PythonAdapter()], vocab, clock)

    # Verify "doomed" has a Capability row before removal.
    before = db.exec(select(Capability).where(Capability.cli_slug == "doomed")).all()
    assert len(before) == 1, "setup: doomed must have exactly one Capability row"

    # Second populate: drop "doomed" (1 of 4 = 25% < 30% → no breaker).
    reduced_recs = [r for r in initial_recs if r.slug != "doomed"]
    result = populate(db, FakeSource(reduced_recs), [PythonAdapter()], vocab, clock)

    assert result["removed"] == 1

    # No orphan Capability rows for the removed CLI.
    orphans = db.exec(select(Capability).where(Capability.cli_slug == "doomed")).all()
    assert orphans == [], f"orphan Capability rows remain: {orphans}"

    # No orphan Cli row either.
    removed_cli = db.get(Cli, "doomed")
    assert removed_cli is None, "Cli row for 'doomed' should be deleted"

    # No phantom edges referencing "doomed".
    from core.graph.edges import current_edges
    edges = current_edges(db)
    phantom = [(f, t, v) for (f, t, v) in edges if f == "doomed" or t == "doomed"]
    assert phantom == [], f"phantom edges remain after removal: {phantom}"
