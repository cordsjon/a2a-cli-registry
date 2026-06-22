from rich.console import Console
from core.tui.overview import render_overview

def _console():
    return Console(record=True, width=120)

_CLI = {"slug": "pdf2text", "lang": "python", "description": "pdf to text",
        "health_status": "healthy",
        "capabilities": [{"intent_tags": ["convert"], "input_types": ["file:pdf"],
                          "output_types": ["text:doc"], "side_effect": "none",
                          "confidence": "declared"}]}

def test_renders_cli_slug_and_health():
    c = _console(); render_overview([_CLI], [], console=c)
    text = c.export_text()
    assert "pdf2text" in text and "healthy" in text

def test_renders_capability_confidence_word():
    c = _console(); render_overview([_CLI], [], console=c)
    assert "declared" in c.export_text()

def test_renders_inferred_distinctly():
    inferred = {**_CLI, "capabilities": [{**_CLI["capabilities"][0], "confidence": "inferred"}]}
    c = _console(); render_overview([inferred], [], console=c)
    assert "inferred" in c.export_text()

def test_renders_edge_line():
    c = _console()
    render_overview([_CLI], [{"from": "pdf2text", "to": "summarize", "via_type": "text:doc"}], console=c)
    text = c.export_text()
    assert "pdf2text" in text and "summarize" in text and "text:doc" in text

def test_empty_catalog_message():
    c = _console(); render_overview([], [], console=c)
    assert "empty" in c.export_text().lower()
