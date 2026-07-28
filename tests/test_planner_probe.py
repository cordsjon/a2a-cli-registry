"""The plan-probe grounding CLI: presence + hop-exclusion + chain position."""
from core.discovery.cli_audit_source import CliAuditSource
from core.adapters.python_adapter import PythonAdapter
from core.vocabulary import VocabularyRegistry
from core.populate import populate
from core.planner import probe as probe_mod


def _fleet(db, clock):
    src = CliAuditSource("tests/golden_clis/fleet.json")
    vocab = VocabularyRegistry(
        registered={"file:pdf", "text:doc", "text:summary"}, aliases={})
    populate(db, src, [PythonAdapter()], vocab, clock)


def test_probe_reports_position_for_a_reachable_slug(db, clock):
    _fleet(db, clock)
    result = probe_mod.probe(db, "pdf2text", ["file:pdf"], ["text:summary"])

    assert result["presence"]["registered"] is True
    assert result["presence"]["capability_rows"] > 0
    assert result["reachable"] is True
    assert result["positions"][0]["position"] == 0
    assert result["hop_excluded"]["excluded"] is False


def test_probe_reports_absence_for_an_unknown_slug(db, clock):
    _fleet(db, clock)
    result = probe_mod.probe(db, "send_mail", ["file:pdf"], ["text:summary"])

    assert result["presence"]["registered"] is False
    assert result["presence"]["capability_rows"] == 0
    # No capability rows => never a candidate hop, and that is the stated reason
    # rather than a misleading "passes the prune".
    assert result["hop_excluded"]["excluded"] is True
    assert "no Capability rows" in result["hop_excluded"]["reason"]
    assert result["reachable"] is False
    assert result["positions"] == []


def test_csv_and_repeated_flags_parse_the_same():
    assert probe_mod._csv(["text,file:pdf"]) == ["text", "file:pdf"]
    assert probe_mod._csv(["text", "file:pdf"]) == ["text", "file:pdf"]
    assert probe_mod._csv([]) == []


def test_render_names_the_absent_case(db, clock):
    _fleet(db, clock)
    result = probe_mod.probe(db, "send_mail", ["file:pdf"], ["text:summary"])
    assert "ABSENT from every planned chain" in probe_mod._render(result)
