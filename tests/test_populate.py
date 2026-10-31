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


def _rec(slug, ins, outs, source_class="cli_audit"):
    # source_class defaults to the feed-owned class so the removal tests below
    # keep exercising removal (US-CLIREG-POPULATE-DELETE-GUARD-01: populate()
    # removes feed-owned rows only).
    return CliRecord(slug=slug, lang="python", path="/x", bucket=None, project=None,
                     description="", source_class=source_class, source_run_id="r",
                     declared_capability=CapabilityRecord(
                         intent_tags=["convert"], input_types=ins, output_types=outs,
                         side_effect="none", confidence="declared"))


def _hand_registered(db, slug, source_class="manual-register"):
    """A row the feed never owned (register_cli.py / bf-batch route)."""
    db.add(Cli(slug=slug, lang="python", path="/y", source_class=source_class))
    db.add(Capability(cli_slug=slug, intent_tags="convert", input_types="file:pdf",
                      output_types="text:doc", side_effect="none", confidence="declared",
                      provenance="manual"))
    db.commit()


_FOUR = [("pdf2text", ["file:pdf"], ["text:doc"]), ("summarize", ["text:doc"], ["text:summary"]),
         ("reporter", ["text:summary"], ["text:report"]), ("doomed", ["file:pdf"], ["text:doc"])]
_VOCAB4 = {"file:pdf", "text:doc", "text:summary", "text:report"}


def test_populate_never_removes_rows_the_feed_does_not_own(db, clock):
    """US-CLIREG-POPULATE-DELETE-GUARD-01 AC-02. Measured 2026-10-30: the
    committed feed (479 slugs) would have removed 165 of 641 live rows, 159 of
    them hand-registered (manual-register, external:nosignups, manual_spec3)
    and under the 30 % breaker. A row whose source_class is not feed-owned is
    never removed, whatever the feed says."""
    vocab = VocabularyRegistry(registered=_VOCAB4, aliases={})
    populate(db, FakeSource([_rec(*r) for r in _FOUR]), [PythonAdapter()], vocab, clock)
    _hand_registered(db, "bf_batch")
    _hand_registered(db, "nosignups_cli", source_class="external:nosignups")
    # a feed that lacks all of them and drops one of its own rows
    reduced = [_rec(*r) for r in _FOUR if r[0] != "doomed"]
    result = populate(db, FakeSource(reduced), [PythonAdapter()], vocab, clock)
    assert result["removed"] == 1                      # doomed only
    assert db.get(Cli, "doomed") is None
    assert db.get(Cli, "bf_batch") is not None
    assert db.get(Cli, "nosignups_cli") is not None
    assert result["protected"] == {"external:nosignups": ["nosignups_cli"],
                                   "manual-register": ["bf_batch"]}


def test_populate_dry_run_reports_removals_grouped_and_writes_nothing(db, clock):
    """AC-01: dry_run prints the would-be removals grouped by source_class
    before any write; the DB is byte-for-byte untouched afterwards."""
    vocab = VocabularyRegistry(registered=_VOCAB4, aliases={})
    populate(db, FakeSource([_rec(*r) for r in _FOUR]), [PythonAdapter()], vocab, clock)
    _hand_registered(db, "bf_batch")
    before = sorted((c.slug, c.source_class, c.updated_at) for c in db.exec(select(Cli)).all())
    reduced = [_rec(*r) for r in _FOUR if r[0] != "doomed"] + [_rec("newcomer", ["file:pdf"], ["text:doc"])]
    plan = populate(db, FakeSource(reduced), [PythonAdapter()], vocab, clock, dry_run=True)
    assert plan["dry_run"] is True
    assert plan["would_remove"] == {"cli_audit": ["doomed"]}
    assert plan["protected"] == {"manual-register": ["bf_batch"]}
    assert plan["would_add"] == 1
    after = sorted((c.slug, c.source_class, c.updated_at) for c in db.exec(select(Cli)).all())
    assert after == before
    assert db.get(Cli, "newcomer") is None


def test_populate_dry_run_reports_breaker_instead_of_raising(db, clock):
    vocab = VocabularyRegistry(registered={"file:pdf", "text:doc"}, aliases={})
    populate(db, FakeSource([_rec("a", ["file:pdf"], ["text:doc"]),
                             _rec("b", ["file:pdf"], ["text:doc"])]), [PythonAdapter()], vocab, clock)
    plan = populate(db, FakeSource([]), [PythonAdapter()], vocab, clock, dry_run=True)
    assert plan["breaker_would_trip"] is True
    assert plan["would_remove"] == {"cli_audit": ["a", "b"]}
    assert db.get(Cli, "a") is not None


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
    honours. Since the capability-map phase 0 (Task 3), populate() also keeps
    'static' and 'llm' rows (PRESERVED_PROVENANCE); only provenance None is
    overwritable.
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


def _seed_cli(db, description):
    db.add(Cli(slug="tool", lang="python", description=description))


def test_populate_preserves_backfilled_capability_row(db, clock):
    _seed_cli(db, "old")
    db.add(Capability(cli_slug="tool", intent_tags="export", input_types="path", output_types="json",
                      side_effect="none", confidence="inferred", provenance="llm"))
    db.commit()
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    populate(db, FakeSource([_rec("tool", ["text"], ["text"])]), [PythonAdapter()], vocab, clock)
    caps = db.exec(select(Capability).where(Capability.cli_slug == "tool")).all()
    assert [(c.provenance, c.intent_tags, c.input_types) for c in caps] == [("llm", "export", "path")]


@pytest.mark.parametrize("marker", ["llm", "manual"])
def test_populate_keeps_description_when_backfilled(db, clock, marker):
    _seed_cli(db, "Exports things to JSON.")
    db.add(Capability(cli_slug="tool", intent_tags="", input_types="", output_types="",
                      side_effect="unknown", confidence="inferred", description_provenance=marker))
    db.commit()
    rec = _rec("tool", ["text"], ["text"]); rec.description = "scripts/tool.py"
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)
    assert db.get(Cli, "tool").description == "Exports things to JSON."
    populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)  # second run: the marker must survive the row recreation
    assert db.get(Cli, "tool").description == "Exports things to JSON."
    assert db.exec(select(Capability).where(Capability.cli_slug == "tool")).one().description_provenance == marker


def test_populate_still_overwrites_feed_owned_rows(db, clock):
    _seed_cli(db, "old")
    db.add(Capability(cli_slug="tool", intent_tags="x", input_types="x", output_types="x",
                      side_effect="none", confidence="inferred"))
    db.commit()
    rec = _rec("tool", ["text"], ["text"]); rec.description = "scripts/tool.py"
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)
    assert db.get(Cli, "tool").description == "scripts/tool.py"
    assert db.exec(select(Capability).where(Capability.cli_slug == "tool")).one().intent_tags == "convert"


def _rec_at(slug, path):
    return CliRecord(slug=slug, lang="python", path=str(path), bucket=None, project=None,
                     description="", source_class="cli_audit", source_run_id="r",
                     declared_capability=None)


def test_populate_drops_feed_rows_whose_path_is_gone(db, clock, tmp_path):
    """AC-05: 28 cli_audit rows pointed at deleted scripts, and every feed run
    re-listed them. A dropped row is then absent from the feed like any other."""
    vocab = VocabularyRegistry(registered=_VOCAB4, aliases={})
    live = tmp_path / "live.py"
    live.write_text("")
    gone = tmp_path / "gone.py"
    module_form = _rec_at("module_form", "")
    db.add(Cli(slug="gone", lang="python", path=str(gone), source_class="cli_audit"))
    for i in range(4):                                 # stay under the 30 % breaker
        _hand_registered(db, f"h{i}")
    db.commit()

    result = populate(db, FakeSource([_rec_at("live", live), _rec_at("gone", gone), module_form]),
                      [PythonAdapter()], vocab, clock, drop_missing_paths=True)

    assert result["dropped_missing_path"] == ["gone"]
    assert result["removed"] == 1
    assert db.get(Cli, "gone") is None
    assert db.get(Cli, "live") is not None
    assert db.get(Cli, "module_form") is not None      # no path to check


def test_populate_keeps_missing_paths_unless_asked(db, clock, tmp_path):
    vocab = VocabularyRegistry(registered=_VOCAB4, aliases={})
    result = populate(db, FakeSource([_rec_at("gone", tmp_path / "gone.py")]),
                      [PythonAdapter()], vocab, clock)
    assert result["dropped_missing_path"] == []
    assert db.get(Cli, "gone") is not None


def test_populate_dropping_missing_paths_still_trips_the_breaker(db, clock, tmp_path):
    """An unmounted volume makes every path look deleted. That must fail closed."""
    vocab = VocabularyRegistry(registered=_VOCAB4, aliases={})
    recs = [_rec_at(f"c{i}", tmp_path / f"c{i}.py") for i in range(4)]
    populate(db, FakeSource(recs), [PythonAdapter()], vocab, clock)
    with pytest.raises(MassRemovalBreaker):
        populate(db, FakeSource(recs), [PythonAdapter()], vocab, clock, drop_missing_paths=True)
    assert db.get(Cli, "c0") is not None


def test_populate_dry_run_reports_dropped_paths(db, clock, tmp_path):
    vocab = VocabularyRegistry(registered=_VOCAB4, aliases={})
    gone = tmp_path / "gone.py"
    db.add(Cli(slug="gone", lang="python", path=str(gone), source_class="cli_audit"))
    db.commit()
    plan = populate(db, FakeSource([_rec_at("gone", gone)]), [PythonAdapter()], vocab, clock,
                    drop_missing_paths=True, dry_run=True)
    assert plan["dropped_missing_path"] == ["gone"]
    assert plan["would_remove"] == {"cli_audit": ["gone"]}
    assert db.get(Cli, "gone") is not None
