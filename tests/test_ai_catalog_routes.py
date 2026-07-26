from fastapi.testclient import TestClient
from core.server.app import create_app


def _client(app_session_factory):
    return TestClient(create_app(app_session_factory), raise_server_exceptions=False)


def test_ai_catalog_route_no_auth(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BASE_URL", "http://reg.example.com:9113")
    monkeypatch.delenv("ARD_PUBLISHER", raising=False)
    resp = _client(app_session_factory).get("/.well-known/ai-catalog.json")
    assert resp.status_code == 200
    cat = resp.json()
    assert cat["specVersion"] == "1.0"
    # publisher defaults to the hostname of A2A_BASE_URL
    assert cat["entries"][0]["identifier"] == "urn:air:reg.example.com:agent:catalog"
    # AC-1.3: urls derive from A2A_BASE_URL
    assert cat["entries"][1]["url"] == "http://reg.example.com:9113/.well-known/mcp-server-card.json"


def test_ard_publisher_env_overrides_hostname(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BASE_URL", "http://100.92.111.112:9113")
    monkeypatch.setenv("ARD_PUBLISHER", "mini.tailnet.example")
    cat = _client(app_session_factory).get("/.well-known/ai-catalog.json").json()
    assert cat["entries"][0]["identifier"].startswith("urn:air:mini.tailnet.example:")


def test_mcp_server_card_route_no_auth(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BASE_URL", "http://reg.example.com:9113")
    resp = _client(app_session_factory).get("/.well-known/mcp-server-card.json")
    assert resp.status_code == 200
    assert resp.json()["endpoint"] == "http://reg.example.com:9113/mcp"
