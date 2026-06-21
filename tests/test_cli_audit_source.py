import json
import pytest
from core.discovery.cli_audit_source import CliAuditSource, SchemaError


def test_discovers_declared_capability(tmp_path):
    src_path = "tests/fixtures/cli_audit_sample.json"
    recs = CliAuditSource(src_path).discover()
    assert len(recs) == 1
    assert recs[0].slug == "pdf2text"
    assert recs[0].declared_capability.input_types == ["file:pdf"]
    assert recs[0].declared_capability.confidence == "declared"


def test_schema_drift_loud_fails(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"clis": [{"lang": "python"}]}))  # missing slug
    with pytest.raises(SchemaError):
        CliAuditSource(str(bad)).discover()
