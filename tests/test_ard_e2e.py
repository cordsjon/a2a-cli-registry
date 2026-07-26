"""AC-2.2: a consumer walks the FULL discovery chain with no hardcoded paths:
catalog -> mcp entry -> server-card -> endpoint -> MCP initialize + tools/list.

Every path after hop 1 is read out of the PREVIOUS hop's response body, so this
test fails the moment any link of the chain stops agreeing with the next.
"""
import json

from fastapi.testclient import TestClient
from core.server.app import create_app

_TOKEN = "e2e-secret"
_BASE = "http://testserver"


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


def test_full_ard_chain_reaches_tools(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    monkeypatch.setenv("A2A_BASE_URL", _BASE)

    app = create_app(app_session_factory)
    # TestClient MUST be a context manager so the parent lifespan starts the MCP
    # StreamableHTTPSessionManager (see tests/test_mcp_http.py).
    with TestClient(app, raise_server_exceptions=False) as client:
        # hop 1: the catalog is public — no auth header.
        cat_resp = client.get("/.well-known/ai-catalog.json")
        assert cat_resp.status_code == 200
        cat = cat_resp.json()
        entry = next(
            e for e in cat["entries"]
            if e["type"] == "application/mcp-server-card+json"
        )

        # hop 2: server-card document — path taken FROM the catalog entry.
        card_path = entry["url"].removeprefix(_BASE)
        card_resp = client.get(card_path)
        assert card_resp.status_code == 200, (
            f"catalog advertised {entry['url']!r} but it does not resolve"
        )
        card = card_resp.json()

        # hop 3: the live endpoint — path taken FROM the server-card.
        endpoint_path = card["endpoint"].removeprefix(_BASE)
        assert endpoint_path == "/mcp"

        headers = {
            "Authorization": f"Bearer {_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        init = client.post(endpoint_path + "/", headers=headers, json={
            "jsonrpc": "2.0", "method": "initialize", "id": 1,
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "ard-e2e", "version": "0.0.1"}},
        })
        assert init.status_code == 200, (
            f"server-card endpoint {card['endpoint']!r} did not accept "
            f"initialize: {init.status_code} {init.text!r}"
        )
        session_id = init.headers.get("mcp-session-id")
        if session_id:
            headers["mcp-session-id"] = session_id

        client.post(endpoint_path + "/", headers=headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"})

        # hop 4: tools/list over the discovered endpoint.
        listed = client.post(endpoint_path + "/", headers=headers, json={
            "jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}})
        assert listed.status_code == 200
        msgs = _parse_sse(listed.text) or [listed.json()]
        tools = next(m["result"]["tools"] for m in msgs if "result" in m)
        assert len(tools) >= 1
