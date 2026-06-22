"""MCP served over Streamable HTTP, mounted on the same ASGI app as REST+A2A.

Tools are rendered from the SHARED op registry (core.ops_registry.OPS) — the
exact same set the in-process MCP surface (core.mcp.server) exposes — so the two
can never drift. Each tool forwards to call_mcp_tool, which validates input
against the op's input_schema and returns a structured content block.

Transport security: DNS-rebinding protection stays ON. Allowed hosts are derived
from A2A_BASE_URL (default http://localhost:8080) plus localhost variants and
"testserver" (the synthetic Host header used by FastAPI TestClient). This replaces
the old host="0.0.0.0" workaround, which disabled DNS-rebinding protection entirely.
"""
import inspect
import os
import warnings
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic.json_schema import PydanticJsonSchemaWarning

from core.ops_registry import OPS
from core.mcp.server import call_mcp_tool


class _Unset:
    """Sentinel for 'argument not supplied by the client'.

    Distinct from None so an explicit None can never be confused with omission.
    Kept out of the advertised inputSchema (its non-serializable default is
    suppressed below), so the schema stays clean.
    """
    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "<unset>"


_MISSING = _Unset()

# JSON-schema "type" -> Python annotation, so FastMCP's func_metadata introspects
# a real per-op signature (top-level params) instead of a single 'arguments' blob.
_TYPE_MAP = {
    "string": str, "array": list, "object": dict,
    "integer": int, "number": float, "boolean": bool,
}


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


def _make_handler(session, op):
    """Return an MCP tool handler bound to *op* and *session*.

    The handler advertises the op's REAL top-level parameters (derived from
    op.input_schema) so a normal MCP client can call e.g.
    `search_cli_catalog {"query":"x"}` with TOP-LEVEL keys — matching the
    in-process call_mcp_tool surface (core/mcp/server.py).

    Why not `def handler(arguments: dict)` or `def handler(**arguments)`:
    mcp 1.28.0's func_metadata introspects the signature. A single
    `arguments: dict` param makes FastMCP advertise
    {"required":["arguments"],...} — forcing clients to NEST under
    {"arguments":{...}}. `**arguments` is advertised by func_metadata as a
    single required STRING param named 'arguments' — also uncallable with
    top-level keys. So we build an explicit signature from input_schema.

    Optional params get the _MISSING sentinel as default; omitted ones are
    stripped before forwarding, so call_mcp_tool receives ONLY the keys the
    client actually sent — identical to the prior pass-through behavior.
    NB: mcp 1.28.0 func_metadata rejects param names starting with '_', so the
    parameters are the op's real schema keys (none start with '_').
    """
    op_name = op.mcp_tool
    schema = op.input_schema
    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    def handler(**arguments):
        clean = {k: v for k, v in arguments.items() if v is not _MISSING}
        # call_mcp_tool re-validates clean against the op's real input_schema.
        return call_mcp_tool(session, op_name, clean)

    # Name the handler after the op so FastMCP's func_metadata titles the
    # advertised inputSchema "<op_name>Arguments" instead of the generic
    # "handlerArguments", and so each registered handler has a distinct
    # __name__ (no cross-op collision in logging/introspection).
    handler.__name__ = op_name
    handler.__qualname__ = op_name

    params = []
    for pname, pschema in props.items():
        annotation = _TYPE_MAP.get(pschema.get("type"), Any)
        if pname in required:
            params.append(inspect.Parameter(
                pname, inspect.Parameter.KEYWORD_ONLY, annotation=annotation))
        else:
            params.append(inspect.Parameter(
                pname, inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation, default=_MISSING))
    handler.__signature__ = inspect.Signature(params)
    handler.__annotations__ = {p.name: p.annotation for p in params}
    return handler


def _mcp_transport_security() -> TransportSecuritySettings:
    """Build TransportSecuritySettings with DNS-rebinding protection ON.

    Allowed hosts are derived from A2A_BASE_URL plus localhost variants and
    "testserver" (FastAPI TestClient's synthetic Host header).
    """
    base = os.environ.get("A2A_BASE_URL", "http://localhost:8080")
    host = urlparse(base).netloc or "localhost:8080"
    # host already equals "localhost:8080" when A2A_BASE_URL is the default,
    # so no hardcoded duplicate — stale over-allowance on non-default ports removed.
    allowed = [host, "localhost", "127.0.0.1", "testserver"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed,
        # base's origin is already captured by f"http://{host}" / f"https://{host}".
        allowed_origins=[f"http://{host}", f"https://{host}"],
    )


def build_mcp_app(session):
    """Build a Streamable-HTTP ASGI app exposing every registry op as an MCP tool.

    *session* is captured by each tool handler. In v1.0 a single session is held
    open for the server's lifetime (see the serve command / mount_mcp).

    streamable_http_path="/" so that when this app is mounted at /mcp by the
    host FastAPI app, Starlette strips the /mcp prefix and the sub-app correctly
    handles the resulting "/" path.

    DNS-rebinding protection is kept ON via transport_security; allowed hosts are
    derived from A2A_BASE_URL (see _mcp_transport_security).
    """
    server = FastMCP(
        "a2a-cli-registry",
        streamable_http_path="/",
        transport_security=_mcp_transport_security(),
    )

    for op in OPS:
        name = op.mcp_tool
        handler = _make_handler(session, op)

        # The handler carries an explicit per-op signature (built from
        # input_schema) so FastMCP advertises the op's REAL top-level params —
        # callable as `tool {"query":"x"}`, NOT `{"arguments":{...}}`.
        # Suppress only the cosmetic PydanticJsonSchemaWarning about the
        # non-serializable _MISSING default (it is intentionally excluded from
        # the advertised schema, keeping inputSchema clean).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", PydanticJsonSchemaWarning)
            server.add_tool(handler, name=name, description=f"Registry op: {name}")

    return server.streamable_http_app()


def mount_mcp(app, mcp_app):
    """Mount a pre-built MCP app at /mcp behind bearer auth.

    The CALLER (create_app) must wire mcp_app.router.lifespan_context into the
    parent FastAPI lifespan before calling this — otherwise the session manager
    never starts and every MCP call 500s.
    """
    app.mount("/mcp", _bearer_gate(mcp_app))
