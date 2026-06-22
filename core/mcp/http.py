"""MCP served over Streamable HTTP, mounted on the same ASGI app as REST+A2A.

Tools are rendered from the SHARED op registry (core.ops_registry.OPS) — the
exact same set the in-process MCP surface (core.mcp.server) exposes — so the two
can never drift. Each tool forwards to call_mcp_tool, which validates input
against the op's input_schema and returns a structured content block.
"""
from mcp.server.fastmcp import FastMCP

from core.ops_registry import OPS
from core.mcp.server import call_mcp_tool


def mcp_tool_names() -> list[str]:
    """The MCP tool names this HTTP surface serves — straight from the registry."""
    return [op.mcp_tool for op in OPS]


def _make_handler(session, op_name: str):
    """Return a handler function bound to op_name and session.

    Uses a factory so each closure captures its own op_name — not the loop
    variable. FastMCP rejects parameter names starting with '_', so we use a
    factory function rather than a default-arg trick.
    """
    def handler(arguments: dict):
        # call_mcp_tool already validates + wraps in a content block.
        return call_mcp_tool(session, op_name, arguments)

    return handler


def build_mcp_app(session):
    """Build a Streamable-HTTP ASGI app exposing every registry op as an MCP tool.

    *session* is captured by each tool handler. In v1.0 a single session is held
    open for the server's lifetime (see the serve command / mount_mcp).
    """
    server = FastMCP("a2a-cli-registry")

    for op in OPS:
        name = op.mcp_tool
        handler = _make_handler(session, name)

        # Register a generic dispatcher tool. FastMCP introspects the handler
        # signature to build the inputSchema — a single 'arguments: dict' param
        # is acceptable for v1.0; real validation happens inside call_mcp_tool.
        server.add_tool(handler, name=name, description=f"Registry op: {name}")

    return server.streamable_http_app()


def mount_mcp(app, session):
    """Mount the MCP Streamable-HTTP app at /mcp on the given FastAPI app."""
    app.mount("/mcp", build_mcp_app(session))
