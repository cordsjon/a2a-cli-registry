from core.cardgen.card import build_agent_card
from core.cardgen.mcp_server_card import build_mcp_server_card


def test_mcp_server_card_shape():
    card = build_mcp_server_card("http://reg:9113")
    assert card == {
        "name": "a2a-cli-registry",
        "endpoint": "http://reg:9113/mcp",
        "transport": "streamable-http",
        "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"},
    }


def test_agent_card_url_points_at_a2a_route():
    # Regression (spec AC-1.5): the JSON-RPC service is POST /a2a, not the base URL.
    card = build_agent_card("http://reg:9113")
    assert card["url"] == "http://reg:9113/a2a"
