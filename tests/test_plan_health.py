"""Test that plan_cli_chain annotates each hop with the CLI's health_status."""
from core.discovery.cli_audit_source import CliAuditSource
from core.adapters.python_adapter import PythonAdapter
from core.vocabulary import VocabularyRegistry
from core.populate import populate
from core.catalog import queries
from core.models import Cli


def test_plan_hops_carry_health_status(db, clock):
    src = CliAuditSource("tests/golden_clis/fleet.json")
    vocab = VocabularyRegistry(
        registered={"file:pdf", "text:doc", "text:summary"}, aliases={})
    populate(db, src, [PythonAdapter()], vocab, clock)

    # set the first hop CLI's health to a known value and commit
    cli = db.get(Cli, "pdf2text")
    cli.health_status = "unhealthy"
    db.add(cli)
    db.commit()

    chains = queries.plan_cli_chain(db, ["file:pdf"], ["text:summary"], [])
    assert chains, "expected at least one chain"

    for hop in chains[0]["hops"]:
        assert "health_status" in hop, f"hop {hop['slug']} missing health_status key"

    first = chains[0]["hops"][0]
    assert first["slug"] == "pdf2text"
    assert first["health_status"] == "unhealthy"
