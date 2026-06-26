"""Enrichment-pass verification. Hermetic: monkeypatches capture_help and
infer_llm_capability so no subprocess or router call is made.

Asserts the load-bearing behaviors:
  - only audit-healthy entries are targeted (healthy_only),
  - inferred capability is written with confidence="inferred",
  - abstention (no help / empty tags) writes NO capability block,
  - the (path,mtime) cache makes a second run a no-op (from_cache),
  - the enriched feed round-trips through the REAL CliAuditSource and the
    confidence survives as "inferred" (the line-36 fix).
"""
from __future__ import annotations

import json

from core.capability.model import CapabilityRecord
from core.discovery.cli_audit_source import CliAuditSource
import bridge.enrich_feed as ef


def _feed():
    return {
        "schema_version": 1,
        "run_id": "t",
        "clis": [
            {"slug": "good", "lang": "python", "path": "/x/good.py",
             "_audit_health": "healthy"},
            {"slug": "nohelp", "lang": "python", "path": "/x/nohelp.py",
             "_audit_health": "healthy"},
            {"slug": "sick", "lang": "python", "path": "/x/sick.py",
             "_audit_health": "unhealthy"},
        ],
    }


def _install_stubs(monkeypatch, mtime=111.0):
    monkeypatch.setattr(ef.os.path, "getmtime", lambda p: mtime)

    def fake_help(path, timeout=5):
        return "" if "nohelp" in path else "Usage: good --convert FILE\nConvert pdf to text"

    def fake_infer(slug, help_text):
        if not help_text.strip():
            return None
        return CapabilityRecord(
            intent_tags=["convert"], input_types=["file:pdf"],
            output_types=["text"], side_effect="none", confidence="inferred",
        )

    monkeypatch.setattr(ef, "capture_help", fake_help)
    monkeypatch.setattr(ef, "infer_llm_capability", fake_infer)


def test_only_healthy_targeted_and_inferred_written(tmp_path, monkeypatch):
    _install_stubs(monkeypatch)
    cache = tmp_path / "cache.json"
    feed = _feed()
    stats = ef.enrich_feed(feed, cache_path=cache, max_workers=2)

    assert stats["targets"] == 2  # 'sick' excluded (unhealthy)
    assert stats["enriched"] == 1  # only 'good'
    assert stats["abstained"] == 1  # 'nohelp'

    good = next(c for c in feed["clis"] if c["slug"] == "good")
    nohelp = next(c for c in feed["clis"] if c["slug"] == "nohelp")
    sick = next(c for c in feed["clis"] if c["slug"] == "sick")
    assert good["capability"]["confidence"] == "inferred"
    assert good["capability"]["input_types"] == ["file:pdf"]
    assert "capability" not in nohelp  # abstained
    assert "capability" not in sick    # never targeted


def test_second_run_uses_cache(tmp_path, monkeypatch):
    _install_stubs(monkeypatch)
    cache = tmp_path / "cache.json"
    ef.enrich_feed(_feed(), cache_path=cache, max_workers=2)
    stats2 = ef.enrich_feed(_feed(), cache_path=cache, max_workers=2)
    assert stats2["from_cache"] == 2  # both healthy entries served from cache


def test_inferred_confidence_survives_real_loader(tmp_path, monkeypatch):
    _install_stubs(monkeypatch)
    cache = tmp_path / "cache.json"
    feed = _feed()
    ef.enrich_feed(feed, cache_path=cache, max_workers=2)

    feed_path = tmp_path / "feed.json"
    feed_path.write_text(json.dumps(feed), encoding="utf-8")
    recs = CliAuditSource(str(feed_path)).discover()

    good = next(r for r in recs if r.slug == "good")
    assert good.declared_capability is not None
    assert good.declared_capability.confidence == "inferred"  # line-36 fix holds


def test_limit_caps_processing(tmp_path, monkeypatch):
    _install_stubs(monkeypatch)
    cache = tmp_path / "cache.json"
    stats = ef.enrich_feed(_feed(), cache_path=cache, max_workers=2, limit=1)
    assert stats["targets"] == 1
