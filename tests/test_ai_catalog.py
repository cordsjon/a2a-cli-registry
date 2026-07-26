import json
from pathlib import Path

import jsonschema

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
