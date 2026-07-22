import pytest
import tools.description_regenerator as regen


def test_normal_source_produces_description(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"description": "Converts CSV files to JSON."}
    monkeypatch.setattr(regen, "_call_router", fake_router)
    result = regen.regenerate_description("csv2json", "def main(): pass")
    assert result == "Converts CSV files to JSON."


def test_old_corrupted_description_never_passed_to_model(monkeypatch):
    captured = {}

    def fake_router(prompt, slug, timeout=30):
        captured["prompt"] = prompt
        return {"description": "does something"}

    monkeypatch.setattr(regen, "_call_router", fake_router)
    regen.regenerate_description("mytool", "def main(): pass")
    assert "ModuleNotFoundError" not in captured["prompt"]
    assert "30_SVG-PAINT" not in captured["prompt"]


def test_empty_source_returns_placeholder_never_crashes(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        raise AssertionError("router must not be called for empty source")
    monkeypatch.setattr(regen, "_call_router", fake_router)
    result = regen.regenerate_description("emptytool", "")
    assert result == "unknown purpose (emptytool)"


def test_unreadable_source_returns_placeholder(monkeypatch):
    result = regen.regenerate_description("badtool", None)
    assert result == "unknown purpose (badtool)"


def test_malformed_model_output_returns_placeholder_not_exception(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return None  # simulates network/JSON failure, same contract as bridge/llm_infer.py
    monkeypatch.setattr(regen, "_call_router", fake_router)
    result = regen.regenerate_description("flakytool", "def main(): pass")
    assert result == "unknown purpose (flakytool)"


def test_extract_context_pulls_docstring_and_signature():
    source = '''
"""Converts CSV files to JSON format."""
import argparse

def main(input_path, output_path):
    """Runs the conversion."""
    pass
'''
    context = regen._extract_context(source)
    assert "Converts CSV files to JSON format." in context
    assert "Runs the conversion." in context
