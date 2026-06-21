# core/mcp/server.py
"""MCP surface. The capability model maps to each tool's INPUT schema only.
A catalogued CLI's output_types are result *content*, NOT a declared tool
outputSchema (category-error fix). Transport is Streamable HTTP, mounted on the
same ASGI app as REST+A2A; auth composes with the A2A bearer."""
from core.ops_registry import OPS, op_by_mcp_tool


def build_mcp_tools() -> list[dict]:
    return [{"name": o.mcp_tool, "description": o.canonical_id,
             "inputSchema": o.input_schema} for o in OPS]
    # deliberately NO outputSchema keyed off output_types


def call_mcp_tool(session, name: str, arguments: dict) -> dict:
    op = op_by_mcp_tool(name)
    payload = op.handler(session, **arguments)
    # structured JSON content block — capability model appears INSIDE as data
    return {"content": [{"type": "json", "json": payload}]}
