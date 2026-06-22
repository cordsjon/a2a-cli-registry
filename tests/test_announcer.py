# tests/test_announcer.py
"""Network-free tests for core/announcer/announcer.py.

All network calls (httpx.post) and the SSRF guard (_is_ssrf_target) are
monkeypatched so no real connections are made.
"""
import json
import types

import httpx
import pytest

from core.announcer.announcer import announce
from core.notifier.bus import sign


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_200(*args, **kwargs):
    """Fake httpx.post that always returns HTTP 200."""
    return types.SimpleNamespace(status_code=200)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_announce_skips_ssrf_target(monkeypatch):
    """A broker that the SSRF guard flags must not be posted to; result is False."""
    posted_urls = []

    def fake_post(url, **kwargs):
        posted_urls.append(url)
        return types.SimpleNamespace(status_code=200)

    # Patch _is_ssrf_target as it is referenced in the announcer module.
    monkeypatch.setattr("core.announcer.announcer._is_ssrf_target", lambda url: True)
    monkeypatch.setattr(httpx, "post", fake_post)

    result = announce(
        "http://example.com/agent.json",
        ["http://internal-broker.local/register"],
    )

    assert result == [False]
    assert posted_urls == [], "httpx.post must NOT be called for SSRF-blocked broker"


def test_announce_signs_when_secret_set(monkeypatch):
    """When A2A_ANNOUNCE_SECRET is set, X-Hub-Signature-256 header is sent."""
    secret = "test-secret-abc"
    captured = {}

    def fake_post(url, **kwargs):
        captured["headers"] = dict(kwargs.get("headers", {}))
        captured["content"] = kwargs.get("content")
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr("core.announcer.announcer._is_ssrf_target", lambda url: False)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("A2A_ANNOUNCE_SECRET", secret)

    card_url = "http://example.com/agent.json"
    announce(card_url, ["http://broker.example.com/register"])

    assert "X-Hub-Signature-256" in captured["headers"], "Signature header must be present"

    # Reproduce the body the announcer builds (same separators) and verify digest.
    body_bytes = json.dumps({"card_url": card_url}, separators=(",", ":")).encode()
    expected_sig = "sha256=" + sign(secret, body_bytes)
    assert captured["headers"]["X-Hub-Signature-256"] == expected_sig


def test_announce_unsigned_when_no_secret(monkeypatch):
    """Without A2A_ANNOUNCE_SECRET, no X-Hub-Signature-256 header is sent."""
    captured = {}

    def fake_post(url, **kwargs):
        captured["headers"] = dict(kwargs.get("headers", {}))
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr("core.announcer.announcer._is_ssrf_target", lambda url: False)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.delenv("A2A_ANNOUNCE_SECRET", raising=False)

    announce("http://example.com/agent.json", ["http://broker.example.com/register"])

    assert "X-Hub-Signature-256" not in captured.get("headers", {}), \
        "No signature header when secret is absent"


def test_announce_isolates_failing_broker(monkeypatch):
    """One broker raising ConnectError must not abort the loop — bulkhead check."""
    call_count = {"n": 0}

    def fake_post(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr("core.announcer.announcer._is_ssrf_target", lambda url: False)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.delenv("A2A_ANNOUNCE_SECRET", raising=False)

    result = announce(
        "http://example.com/agent.json",
        ["http://broker-a.example.com/register", "http://broker-b.example.com/register"],
    )
    assert result == [False, True]


def test_announce_empty_brokers_returns_empty(monkeypatch):
    """Empty broker list returns an empty result list."""
    monkeypatch.setattr("core.announcer.announcer._is_ssrf_target", lambda url: False)
    result = announce("http://example.com/agent.json", [])
    assert result == []
