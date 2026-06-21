from core.discovery.base import CliRecord, DiscoverySource


def test_clirecord_holds_declared_capability():
    rec = CliRecord(slug="pdf2text", lang="python", path="/x", bucket="b",
                    project="p", description="d", declared_capability=None,
                    source_class="cli_audit", source_run_id="r1")
    assert rec.slug == "pdf2text"


def test_discovery_source_is_a_protocol():
    class Fake:
        def discover(self): return []
    assert isinstance(Fake(), DiscoverySource)
