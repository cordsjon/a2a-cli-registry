import tools.capability_repair as repair


def test_normal_repair_returns_proposal_shape(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {
            "description": "Seeds the topics table in the app SQLite database; takes no arguments.",
            "input_types": [],
            "output_types": ["text"],
            "intent_tags": ["seed", "insert"],
            "side_effect": "writes-fs",
        }
    monkeypatch.setattr(repair, "_call_router", fake_router)
    result = repair.repair_row(
        "seed_topics",
        "Seeds the topics table.",
        {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "none",
         "confidence": "inferred", "provenance": "llm"},
        "side_effect 'none' contradicts database seeding",
        "def main(): pass",
    )
    assert result["slug"] == "seed_topics"
    assert result["description"].startswith("Seeds the topics table in the app SQLite database")
    assert result["capability"]["side_effect"] == "writes-fs"
    assert result["capability"]["intent_tags"] == ["seed", "insert"]
    assert result["capability"]["provenance"] == "llm"
    assert result["capability"]["confidence"] == "inferred"


def test_router_failure_returns_none(monkeypatch):
    monkeypatch.setattr(repair, "_call_router", lambda prompt, slug, timeout=30: None)
    result = repair.repair_row("x", "desc", {"input_types": [], "output_types": [],
                                             "intent_tags": [], "side_effect": "unknown",
                                             "confidence": "inferred", "provenance": "llm"},
                               "reason", "")
    assert result is None


def test_invalid_side_effect_clamped_to_unknown(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"description": "d", "input_types": ["path"], "output_types": ["path"],
                "intent_tags": ["seed"], "side_effect": "explodes"}
    monkeypatch.setattr(repair, "_call_router", fake_router)
    result = repair.repair_row("x", "desc", {"input_types": [], "output_types": [],
                                             "intent_tags": [], "side_effect": "none",
                                             "confidence": "inferred", "provenance": "static"},
                               "reason", "")
    assert result["capability"]["side_effect"] == "unknown"


def test_missing_description_keeps_original(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"input_types": ["path"], "output_types": ["path"],
                "intent_tags": ["seed"], "side_effect": "writes-fs"}
    monkeypatch.setattr(repair, "_call_router", fake_router)
    result = repair.repair_row("x", "original description",
                               {"input_types": [], "output_types": [], "intent_tags": [],
                                "side_effect": "none", "confidence": "inferred", "provenance": "llm"},
                               "reason", "")
    assert result["description"] == "original description"


def test_capability_none_repairs_description_only(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"description": "A clearer description.", "input_types": ["path"],
                "output_types": ["text"], "intent_tags": ["report"], "side_effect": "none"}
    monkeypatch.setattr(repair, "_call_router", fake_router)
    result = repair.repair_row("shellwrap", "unknown purpose (shellwrap)", None, "uninformative", "")
    assert result["description"] == "A clearer description."
    assert result["capability"] is None
