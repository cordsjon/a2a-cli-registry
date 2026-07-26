"""ARD v1.0 ai-catalog.json capability manifest builder."""


def build_ai_catalog(base_url: str, publisher: str) -> dict:
    """ARD v1.0 capability manifest (reference-only, Option C).

    Entry urls point at artifact DOCUMENTS (ARD §3.4), never live endpoints.
    `publisher` should be an FQDN (ARD §4.2.1); a tailnet IP is a documented
    conformance exception (spec Risk 4).
    """
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "a2a-cli-registry",
            "documentationUrl": "https://github.com/cordsjon/a2a-cli-registry",
        },
        "entries": [
            {
                "identifier": f"urn:air:{publisher}:agent:catalog",
                "displayName": "a2a-cli-registry Agent",
                "type": "application/a2a-agent-card+json",
                "url": f"{base_url}/.well-known/agent-card.json",
                "description": "Capability-typed catalog of local CLIs (describe + plan only).",
                "tags": ["cli", "registry", "planning", "local-first"],
                "representativeQueries": [
                    "which local CLI tools are available on this machine",
                    "plan a chain of CLI tools to convert a PDF into a summary",
                    "is a given local CLI healthy right now",
                ],
            },
            {
                "identifier": f"urn:air:{publisher}:mcp:server",
                "displayName": "a2a-cli-registry MCP Server",
                "type": "application/mcp-server-card+json",
                "url": f"{base_url}/.well-known/mcp-server-card.json",
                "description": "MCP Streamable-HTTP endpoint exposing discovery + plan tools (bearer auth).",
                "tags": ["mcp", "streamable-http", "cli", "registry"],
                "representativeQueries": [
                    "list the MCP tools this registry exposes",
                    "search the local CLI fleet by capability over MCP",
                ],
            },
        ],
    }
