from core.mcp.http import build_mcp_app
from core.mcp.server import build_mcp_tools
from fastapi.testclient import TestClient
from core.server.app import create_app

_TOKEN = "test-secret-token"


def test_mcp_http_app_is_asgi_and_exposes_registry_tools():
    # build_mcp_app returns a mounted ASGI app; its tool set == the shared registry
    app = build_mcp_app(session=None)   # tool LIST does not need a live session
    assert app is not None
    assert callable(app)                # ASGI app is callable
    # parity: the tool names the HTTP surface advertises == build_mcp_tools()
    from core.mcp.http import mcp_tool_names
    assert set(mcp_tool_names()) == {t["name"] for t in build_mcp_tools()}


def test_mcp_endpoint_requires_auth(db, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app, raise_server_exceptions=False)
    # No auth header -> rejected (401/403). MCP Streamable-HTTP uses POST.
    resp = client.post("/mcp", json={})
    assert resp.status_code in (401, 403)


def test_mcp_endpoint_mounted_and_authed_reachable(db, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app, raise_server_exceptions=False)
    # With a valid token the route exists (not 404) — exact MCP handshake body
    # is exercised by the SDK; here we assert the mount + auth gate, not 404/401.
    resp = client.post("/mcp", headers={"Authorization": f"Bearer {_TOKEN}"},
                       json={"jsonrpc": "2.0", "method": "ping", "id": 1})
    assert resp.status_code != 404      # mounted
    assert resp.status_code != 401      # authed through the gate
