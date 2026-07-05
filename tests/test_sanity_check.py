import pytest
import tools.sanity_check as sanity


def test_coherent_row_passes(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"ok": True, "reason": "clear purpose"}
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "csv2json",
        "Converts CSV files to JSON format.",
        {"input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"], "side_effect": "none"},
    )
    assert result["ok"] is True


def test_path_like_description_rejected_by_mechanical_prefilter_no_router_call(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        raise AssertionError("router must not be called for path-like description")
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "brokentool",
        "30_SVG-PAINT/scripts/ppv-dashboard.py",
        {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
    )
    assert result["ok"] is False
    assert "path-like" in result["reason"] or "traceback" in result["reason"]


def test_traceback_like_description_rejected_by_mechanical_prefilter(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        raise AssertionError("router must not be called for traceback-like description")
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "brokentool2",
        "ModuleNotFoundError: No module named 'portalocker'",
        {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
    )
    assert result["ok"] is False


def test_mismatched_garbage_not_path_shaped_goes_through_llm(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"ok": False, "reason": "description does not match capability fields"}
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "weirdtool",
        "does stuff sometimes maybe",
        {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
    )
    assert result["ok"] is False
    assert result["reason"]


def test_ambiguous_model_output_fails_closed(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return None  # simulates malformed/unparseable model output
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "ambiguoustool",
        "a reasonably normal-sounding description",
        {"input_types": ["path"], "output_types": ["json"], "intent_tags": [], "side_effect": "none"},
    )
    assert result["ok"] is False


def test_calibration_set_has_known_good_and_bad_cases():
    assert len(sanity.CALIBRATION_SET) >= 8
    goods = [c for c in sanity.CALIBRATION_SET if c["expected_ok"]]
    bads = [c for c in sanity.CALIBRATION_SET if not c["expected_ok"]]
    assert goods
    assert bads


def test_malformed_router_output_retried_once(monkeypatch):
    calls = {"n": 0}

    def flaky_router(prompt, slug, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return {"ok": True, "reason": "fine"}

    monkeypatch.setattr(sanity, "_call_router", flaky_router)
    result = sanity.check_row("x", "Converts CSV files to JSON.", {"input_types": ["path"]})
    assert calls["n"] == 2
    assert result["ok"] is True


def test_malformed_router_output_fails_after_retry(monkeypatch):
    monkeypatch.setattr(sanity, "_call_router", lambda prompt, slug, timeout=30: None)
    result = sanity.check_row("x", "Converts CSV files to JSON.", {"input_types": ["path"]})
    assert result["ok"] is False
    assert "malformed" in result["reason"]


def test_calibration_set_covers_noarg_and_binary_output_cases():
    assert len(sanity.CALIBRATION_SET) >= 11
    slugs = [c["slug"] for c in sanity.CALIBRATION_SET]
    assert "noarg-seeder" in slugs
    assert "pdf-report" in slugs
    assert "db-seeder-mismatch" in slugs
