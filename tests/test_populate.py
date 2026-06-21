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
