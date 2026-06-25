import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from core.models import Cli, Capability, CliEdge
from core.catalog.queries import export_rows


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed(s):
    s.add(Cli(slug="summarize", lang="python", project="text", path="/bin/sum",
              updated_at=10.0, description="d2", health_status="healthy"))
    s.add(Cli(slug="pdf2text", lang="python", project="docs", path="/bin/p2t",
              updated_at=20.0, description="d1", health_status="healthy"))
    s.add(Capability(cli_slug="pdf2text", intent_tags="document,convert",
                     input_types="file:pdf", output_types="text",
                     side_effect="none", confidence="declared"))
    s.add(Capability(cli_slug="summarize", intent_tags="summarize",
                     input_types="text", output_types="text",
                     side_effect="none", confidence="declared"))
    s.add(CliEdge(from_slug="pdf2text", to_slug="summarize", via_type="text"))
    s.commit()


def test_export_rows_sorted_and_shaped():
    s = _session()
    _seed(s)
    rows = export_rows(s)
    assert [r["slug"] for r in rows] == ["pdf2text", "summarize"]  # by (project, slug): docs<text
    pdf = rows[0]
    assert pdf["path"] == "/bin/p2t" and pdf["updated_at"] == 20.0
    assert pdf["capability"]["intent_tags"] == ["convert", "document"]  # sorted
    assert pdf["edges"] == [{"to": "summarize", "via": "text"}]


def test_export_rows_rejects_multiple_capabilities():
    s = _session()
    _seed(s)
    s.add(Capability(cli_slug="pdf2text", intent_tags="extra",
                     input_types="text", output_types="text",
                     side_effect="none", confidence="declared"))
    s.commit()
    with pytest.raises(ValueError):
        export_rows(s)
