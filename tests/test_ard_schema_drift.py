import json
from pathlib import Path

from scripts.check_ard_schema_drift import compare_schemas, main as drift_main

FIXTURES = Path(__file__).parent / "fixtures"


def test_identical_schemas_report_no_drift():
    doc = json.loads((FIXTURES / "ai-catalog.schema.json").read_text())
    assert compare_schemas(doc, doc) == []


def test_modified_copy_reports_changed_paths(tmp_path):
    # AC-8.1: an artificial change is detected and the changed path named
    upstream = json.loads((FIXTURES / "ai-catalog.schema.json").read_text())
    vendored = json.loads(json.dumps(upstream))
    vendored["properties"]["specVersion"]["enum"] = ["1.0", "1.1"]
    changed = compare_schemas(vendored, upstream)
    assert any("properties.specVersion" in p for p in changed)


def test_cli_exit_codes(tmp_path):
    # AC-8.2: retrieval-date visibility comes from the provenance sidecar
    up = tmp_path / "up.json"; up.write_text('{"a": 1}')
    same = tmp_path / "v.json"; same.write_text('{"a": 1}')
    diff = tmp_path / "d.json"; diff.write_text('{"a": 2}')
    assert drift_main(["--vendored", str(same), "--upstream-json", str(up)]) == 0
    assert drift_main(["--vendored", str(diff), "--upstream-json", str(up)]) == 1
