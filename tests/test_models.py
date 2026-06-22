from core.models import Cli, Capability, CliEdge
from sqlmodel import Session, select


def test_cli_capability_edge_roundtrip(db):
    cli = Cli(slug="pdf2text", lang="python", launch_spec='{"kind":"python_module","entrypoint":"pdf2text"}',
              description="pdf to text", health_status="unknown", enabled=True, a2a_invokable=False)
    cap = Capability(cli_slug="pdf2text", intent_tags="convert,extract",
                     input_types="file:pdf", output_types="text",
                     side_effect="none", confidence="declared")
    edge = CliEdge(from_slug="pdf2text", to_slug="summarize", via_type="text", recomputed_at=1.0)
    db.add(cli); db.add(cap); db.add(edge); db.commit()

    got = db.exec(select(Cli).where(Cli.slug == "pdf2text")).one()
    assert got.a2a_invokable is False
    assert db.exec(select(Capability)).one().confidence == "declared"
    assert db.exec(select(CliEdge)).one().via_type == "text"
