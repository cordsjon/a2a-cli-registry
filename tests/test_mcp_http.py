import json

from core.mcp.http import build_mcp_app
from core.mcp.server import build_mcp_tools
from fastapi.testclient import TestClient
from core.server.app import create_app

_TOKEN = "test-secret-token"


def _mcp_headers(extra=None):
    h = {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if extra:
        h.update(extra)
    return h


def _parse_sse(text):
    """MCP Streamable-HTTP replies are SSE; pull the JSON out of `data:` lines."""
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return out


def test_mcp_http_app_is_asgi_and_exposes_registry_tools():
    # build_mcp_app returns a mounted ASGI app; its tool set == the shared registry
    app = build_mcp_app(session=None)   # tool LIST does not need a live session
    assert app is not None
    assert callable(app)                # ASGI app is callable
    # parity: the tool names the HTTP surface advertises == build_mcp_tools()
    from core.mcp.http import mcp_tool_names
    assert set(mcp_tool_names()) == {t["name"] for t in build_mcp_tools()}


def test_mcp_endpoint_requires_auth(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app, raise_server_exceptions=False)
    # No auth header -> rejected (401/403). MCP Streamable-HTTP uses POST.
    resp = client.post("/mcp", json={})
    assert resp.status_code in (401, 403)


def test_mcp_endpoint_mounted_and_authed_reachable(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    # TestClient MUST be used as a context manager so the parent FastAPI lifespan
    # fires, which starts the MCP StreamableHTTPSessionManager.  Without it the
    # session manager is uninitialized and every real MCP call returns 500.
    with TestClient(app, raise_server_exceptions=False) as client:
        # Minimal valid MCP Streamable-HTTP initialize request.  The initialize
        # method is the standard MCP handshake entry point; it proves the session
        # manager actually started (a missing lifespan yields 500, not 200).
        resp = client.post(
            "/mcp/",
            headers={
                "Authorization": f"Bearer {_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "0.0.1"},
                },
            },
        )
    assert resp.status_code != 404          # mounted
    assert resp.status_code != 401          # authed through the gate
    assert resp.status_code != 500          # session manager was started via lifespan


def test_mcp_tools_call_accepts_top_level_args(app_session_factory, monkeypatch):
    """A real tools/call round-trip with TOP-LEVEL args must SUCCEED.

    Regression guard for the headline bug: when the handler was
    `def handler(arguments: dict)`, FastMCP advertised
    inputSchema={"required":["arguments"],...} and a client sending
    {"query":""} at the top level failed validation. This test FAILS against
    that old signature and PASSES once the handler advertises the op's real
    top-level params. Streamable-HTTP replies are SSE, parsed via _parse_sse.
    """
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        # 1) initialize handshake -> grab the session id
        init = client.post("/mcp/", headers=_mcp_headers(), json={
            "jsonrpc": "2.0", "method": "initialize", "id": 1,
            "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.0.1"},
            },
        })
        assert init.status_code == 200
        sid = init.headers.get("mcp-session-id")
        assert sid

        # 2) notifications/initialized completes the handshake
        client.post(
            "/mcp/",
            headers=_mcp_headers({"mcp-session-id": sid}),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        # 3) tools/list: search_cli_catalog must NOT require a nested "arguments"
        listed = client.post(
            "/mcp/",
            headers=_mcp_headers({"mcp-session-id": sid}),
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
        )
        tools = {
            t["name"]: t
            for m in _parse_sse(listed.text) if "result" in m
            for t in m["result"].get("tools", [])
        }
        schema = tools["search_cli_catalog"]["inputSchema"]
        # The headline bug advertised required==["arguments"]; assert it's gone.
        assert schema.get("required") != ["arguments"]
        assert "query" in schema.get("properties", {})

        # 4) tools/call with TOP-LEVEL args must succeed (not a validation error)
        called = client.post(
            "/mcp/",
            headers=_mcp_headers({"mcp-session-id": sid}),
            json={
                "jsonrpc": "2.0", "method": "tools/call", "id": 3,
                "params": {"name": "search_cli_catalog",
                           "arguments": {"query": ""}},
            },
        )
        results = [m for m in _parse_sse(called.text) if "result" in m]
        assert results, f"no result in tools/call response: {called.text!r}"
        result = results[0]["result"]
        # Top-level call SUCCEEDED: no MCP-level error, no validation error text.
        assert result.get("isError") is not True
        blob = json.dumps(result)
        assert "Field required" not in blob
        assert "validation error" not in blob.lower()
