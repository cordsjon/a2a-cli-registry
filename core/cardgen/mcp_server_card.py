def build_mcp_server_card(base_url: str) -> dict:
    """Minimal MCP server-card document (no canonical schema exists yet —
    keep to these four fields; see spec Risk 2)."""
    return {
        "name": "a2a-cli-registry",
        "endpoint": f"{base_url}/mcp",
        "transport": "streamable-http",
        "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"},
    }
