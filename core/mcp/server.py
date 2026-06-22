# core/mcp/server.py
"""MCP surface. The capability model maps to each tool's INPUT schema only.
A catalogued CLI's output_types are result *content*, NOT a declared tool
outputSchema (category-error fix). Transport is Streamable HTTP, mounted on the
same ASGI app as REST+A2A; auth composes with the A2A bearer."""
from core.ops_registry import OPS, op_by_mcp_tool, validate_input as _validate_input_shared


def build_mcp_tools() -> list[dict]:
    return [{"name": o.mcp_tool, "description": o.canonical_id,
             "inputSchema": o.input_schema} for o in OPS]
    # deliberately NO outputSchema keyed off output_types


def _validate_arguments(op, arguments: dict):
    """Validate argument keys and types against op.input_schema.
    Returns an error string or None. Delegates to shared validate_input in ops_registry."""
    return _validate_input_shared(op, arguments)


def _error_block(msg: str) -> dict:
    """Return a structured error in the same content-block shape as success."""
    return {"content": [{"type": "json", "json": {"error": msg}}]}


def call_mcp_tool(session, name: str, arguments: dict) -> dict:
    try:
        op = op_by_mcp_tool(name)
    except KeyError:
        return _error_block(f"unknown tool: {name}")

    err = _validate_arguments(op, arguments)
    if err:
        return _error_block(err)

    try:
        payload = op.handler(session, **arguments)
    except (TypeError, ValueError) as exc:
        return _error_block(f"invalid input: {exc}")
    # structured JSON content block — capability model appears INSIDE as data
    return {"content": [{"type": "json", "json": payload}]}
