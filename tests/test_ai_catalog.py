import json
from pathlib import Path

import jsonschema
import jsonschema as _js

from core.cardgen.ai_catalog import build_ai_catalog

FIXTURES = Path(__file__).parent / "fixtures"


def _load_schema():
    return json.loads((FIXTURES / "ai-catalog.schema.json").read_text())


def test_vendored_schema_is_valid_draft_2020_12():
    schema = _load_schema()
    # raises if the schema itself is malformed
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["specVersion"]["enum"] == ["1.0"]


def test_provenance_sidecar_exists_and_names_source():
    text = (FIXTURES / "ai-catalog.schema.provenance.md").read_text()
    assert "ards-project/ard-spec" in text
    assert "2026-" in text  # retrieval date present


def test_catalog_validates_against_vendored_schema():
    cat = build_ai_catalog("http://reg:9113", publisher="reg.example.com")
    _js.validate(cat, _load_schema(),
                 format_checker=_js.Draft202012Validator.FORMAT_CHECKER)


def test_catalog_entries_reference_artifact_documents_not_endpoints():
    cat = build_ai_catalog("http://reg:9113", publisher="reg.example.com")
    urls = {e["type"]: e["url"] for e in cat["entries"]}
    # ARD §3.4: url references the artifact DOCUMENT
    assert urls["application/a2a-agent-card+json"] == "http://reg:9113/.well-known/agent-card.json"
    assert urls["application/mcp-server-card+json"] == "http://reg:9113/.well-known/mcp-server-card.json"


def test_catalog_urns_use_publisher():
    cat = build_ai_catalog("http://reg:9113", publisher="reg.example.com")
    ids = [e["identifier"] for e in cat["entries"]]
    assert ids == ["urn:air:reg.example.com:agent:catalog",
                   "urn:air:reg.example.com:mcp:server"]
