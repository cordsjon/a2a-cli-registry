import pytest
import tools.capability_llm_fallback as fallback


def test_normal_response_parsed_into_shape(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {
            "input_types": ["path"],
            "output_types": ["json"],
            "intent_tags": ["convert"],
            "side_effect": "none",
        }
    monkeypatch.setattr(fallback, "_call_router", fake_router)
    result = fallback.infer_capability_llm("mytool", "converts files", "def main(): pass")
    assert result["input_types"] == ["path"]
    assert result["output_types"] == ["json"]
    assert result["intent_tags"] == ["convert"]
    assert result["side_effect"] == "none"
    assert result["provenance"] == "llm"
    assert result["confidence"] == "inferred"


def test_malformed_output_degrades_to_empties_no_crash(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return None
    monkeypatch.setattr(fallback, "_call_router", fake_router)
    result = fallback.infer_capability_llm("mytool", "", "")
    assert result["input_types"] == []
    assert result["output_types"] == []
    assert result["intent_tags"] == []
    assert result["side_effect"] == "unknown"
    assert result["provenance"] == "llm"


def test_partial_model_response_missing_keys_defaults_safely(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"input_types": ["path"]}  # missing everything else
    monkeypatch.setattr(fallback, "_call_router", fake_router)
    result = fallback.infer_capability_llm("mytool", "desc", "src")
    assert result["input_types"] == ["path"]
    assert result["output_types"] == []
    assert result["intent_tags"] == []
    assert result["side_effect"] == "unknown"


def test_invalid_side_effect_clamped_to_unknown(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {
            "input_types": ["path"],
            "output_types": ["json"],
            "intent_tags": ["convert"],
            "side_effect": "deletes-everything",  # invalid value
        }
    monkeypatch.setattr(fallback, "_call_router", fake_router)
    result = fallback.infer_capability_llm("mytool", "desc", "src")
    assert result["side_effect"] == "unknown"
    assert result["input_types"] == ["path"]
    assert result["output_types"] == ["json"]
    assert result["intent_tags"] == ["convert"]


def test_system_prompt_classifies_db_and_new_file_writes_as_writes_fs():
    # Regression: the original prompt inverted the registry's side_effect
    # semantics ("a NEW output file is 'none'"), causing systematic
    # contradictions on DB-seeder CLIs (round-3 sanity failures).
    assert "database" in fallback._SYSTEM.lower()
    assert "NEW output file is 'none'" not in fallback._SYSTEM
    assert "ONLY if the tool modifies an input file in" not in fallback._SYSTEM
