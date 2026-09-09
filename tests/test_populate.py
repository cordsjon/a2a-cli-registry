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


def test_manual_provenance_capability_survives_a_feed_rerun(db, clock):
    """A hand-set capability row marked provenance='manual' must survive the
    delete+recreate in populate().

    Reproduces the live decay: `send_mail` was hand-fixed twice (the §2.2
    intent_tags retag and the AC-01 output_types backfill) and BOTH were erased
    by a feed re-run, leaving two planner tests red for ~2 months. The spec
    predicted it ("populate.py delete+recreate means a future enriched feed can
    restore notify,send; fails closed") but nothing enforced it.

    'manual' is the same protected marker tools/backfill_capabilities.py already
    honours: provenance in (None, 'static', 'llm') is overwritable, anything
    else is not.
    """
    from sqlalchemy import text as _text

    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    recs = [_rec("send_mail", ["text"], [])]
    populate(db, FakeSource(recs), [PythonAdapter()], vocab, clock)

    # Hand-fix the row exactly as an operator would, and mark it manual.
    db.connection().execute(_text(
        "UPDATE capability SET intent_tags='send', output_types='text', "
        "provenance='manual' WHERE cli_slug='send_mail'"
    ))
    db.commit()

    # A feed re-run proposing the ORIGINAL (unfixed) values.
    populate(db, FakeSource(recs), [PythonAdapter()], vocab, clock)

    cap = db.exec(select(Capability).where(Capability.cli_slug == "send_mail")).one()
    assert cap.intent_tags == "send", (
        f"manual intent_tags overwritten by the feed: {cap.intent_tags!r} — "
        "this is the live send_mail decay reproduced"
    )
    assert cap.output_types == "text", (
        f"manual output_types overwritten by the feed: {cap.output_types!r}"
    )


def test_non_manual_capability_is_still_refreshed_by_the_feed(db, clock):
    """The guard must protect ONLY manual rows — a feed-owned row still updates.

    Without this, "preserve manual" could silently become "never update
    anything" and the registry would freeze at its first populate.
    """
    vocab = VocabularyRegistry(registered={"file:pdf", "text:doc", "text:summary"}, aliases={})
    populate(db, FakeSource([_rec("conv", ["file:pdf"], ["text:doc"])]),
             [PythonAdapter()], vocab, clock)
    populate(db, FakeSource([_rec("conv", ["file:pdf"], ["text:summary"])]),
             [PythonAdapter()], vocab, clock)

    cap = db.exec(select(Capability).where(Capability.cli_slug == "conv")).one()
    assert cap.output_types == "text:summary", (
        f"feed-owned row was not refreshed: {cap.output_types!r}"
    )
