"""MCP served over Streamable HTTP, mounted on the same ASGI app as REST+A2A.

Tools are rendered from the SHARED op registry (core.ops_registry.OPS) — the
exact same set the in-process MCP surface (core.mcp.server) exposes — so the two
can never drift. Each tool forwards to call_mcp_tool, which validates input
against the op's input_schema and returns a structured content block.
"""
import os

from mcp.server.fastmcp import FastMCP

from core.ops_registry import OPS
from core.mcp.server import call_mcp_tool


def _bearer_gate(asgi_app):
    """Wrap an ASGI app so requests without a valid bearer token get 401.

    Mirrors core.server.app._require_token: expected token from env
    A2A_BEARER_TOKEN; missing env or wrong/missing token -> 401.
    """
    async def _gated(scope, receive, send):
        if scope["type"] != "http":
            await asgi_app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode()
        expected = os.environ.get("A2A_BEARER_TOKEN")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not expected or token != expected:
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Unauthorized"})
            return
        await asgi_app(scope, receive, send)
    return _gated


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

    streamable_http_path="/" so that when this app is mounted at /mcp by the
    host FastAPI app, Starlette strips the /mcp prefix and the sub-app correctly
    handles the resulting "/" path.
    """
    server = FastMCP("a2a-cli-registry", streamable_http_path="/")

    for op in OPS:
        name = op.mcp_tool
        handler = _make_handler(session, name)

        # Register a generic dispatcher tool. FastMCP introspects the handler
        # signature to build the inputSchema — a single 'arguments: dict' param
        # is acceptable for v1.0; real validation happens inside call_mcp_tool.
        server.add_tool(handler, name=name, description=f"Registry op: {name}")

    return server.streamable_http_app()


def mount_mcp(app, session):
    """Mount the MCP Streamable-HTTP app at /mcp, gated by bearer auth."""
    app.mount("/mcp", _bearer_gate(build_mcp_app(session)))
