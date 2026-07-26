import json
import pytest

from core.ard import resolve as R


def _fake_fetch(payloads):
    """payloads: url -> dict | Exception. Returns a fetch_json stand-in."""
    def fetch(url, deadline, max_bytes=1_048_576):
        v = payloads[url]
        if isinstance(v, Exception):
            raise v
        return v
    return fetch


CATALOG = {
    "specVersion": "1.0",
    "entries": [
        {"identifier": "urn:air:h:agent:catalog", "displayName": "a",
         "type": "application/a2a-agent-card+json",
         "url": "http://reg:9113/.well-known/agent-card.json"},
        {"identifier": "urn:air:h:mcp:server", "displayName": "m",
         "type": "application/mcp-server-card+json",
         "url": "http://reg:9113/.well-known/mcp-server-card.json"},
    ],
}
CARD = {"name": "a2a-cli-registry", "endpoint": "http://reg:9113/mcp",
        "transport": "streamable-http", "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"}}


def test_resolve_mcp_is_two_hop(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/mcp-server-card.json": CARD,
    }))
    assert R.resolve("http://reg:9113", "mcp") == "http://reg:9113/mcp"


def test_resolve_a2a_returns_card_document_url(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch(
        {"http://reg:9113/.well-known/ai-catalog.json": CATALOG}))
    assert R.resolve("http://reg:9113", "a2a") == "http://reg:9113/.well-known/agent-card.json"


def test_no_matching_type_raises_ard_error(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch(
        {"http://reg:9113/.well-known/ai-catalog.json": {"specVersion": "1.0", "entries": []}}))
    with pytest.raises(R.ArdError, match="no entry of type"):
        R.resolve("http://reg:9113", "mcp")


def test_server_card_missing_endpoint_raises(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/mcp-server-card.json": {"name": "x"},
    }))
    with pytest.raises(R.ArdError, match="endpoint"):
        R.resolve("http://reg:9113", "mcp")


def test_bad_scheme_rejected():
    with pytest.raises(R.ArdError, match="scheme"):
        R.resolve("file:///etc/passwd", "mcp")


def test_oversize_body_fails_closed(tmp_path):
    # fetch_json enforces the cap itself — exercise it for real over HTTP
    import http.server, threading, functools
    class Big(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"pad":"' + b"x" * 1_200_000 + b'"}')
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Big)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        with pytest.raises(R.ArdError, match="too large"):
            R.fetch_json(f"http://127.0.0.1:{srv.server_port}/x", deadline=R._now() + 10)
    finally:
        srv.shutdown()
