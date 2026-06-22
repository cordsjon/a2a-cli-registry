import jsonschema
from core.mcp.server import build_mcp_tools, call_mcp_tool
from core.models import Cli, Capability


def test_tool_schema_is_valid_jsonschema_input_only():
    tools = build_mcp_tools()
    plan = next(t for t in tools if t["name"] == "plan_cli_chain")
    jsonschema.Draft7Validator.check_schema(plan["inputSchema"])
    assert "outputSchema" not in plan            # output_types are NOT a tool output-schema


def test_result_is_structured_content_block(db, spawn_spy):
    out = call_mcp_tool(db, "search_cli_catalog", {"query": ""})
    assert out["content"][0]["type"] == "json"   # structured content, capability data inside
    assert spawn_spy == []                        # describe-only on MCP path too


def test_unknown_tool_returns_structured_error(db):
    out = call_mcp_tool(db, "no_such_tool", {})
    # must NOT raise — must return the same content-block shape with an error key
    assert "content" in out
    block = out["content"][0]
    assert block["type"] == "json"
    assert "error" in block["json"]
    assert "no_such_tool" in block["json"]["error"]


def test_unknown_argument_returns_structured_error(db):
    # "search_cli_catalog" accepts only "query"; passing an unexpected key must
    # return a structured error rather than letting TypeError leak out of handler
    out = call_mcp_tool(db, "search_cli_catalog", {"query": "", "injected_key": "bad"})
    assert "content" in out
    block = out["content"][0]
    assert block["type"] == "json"
    assert "error" in block["json"]
    assert "injected_key" in block["json"]["error"]


def test_describe_via_mcp_omits_launch_spec(db):
    """MCP describe_cli path must not expose launch_spec to unauthenticated callers."""
    db.add(Cli(
        slug="secret-cli",
        lang="python",
        launch_spec='{"kind":"python_module","entrypoint":"secret.main"}',
        description="a CLI with a non-empty launch spec",
    ))
    db.add(Capability(
        cli_slug="secret-cli",
        intent_tags="convert",
        input_types="file:pdf",
        output_types="text",
        side_effect="none",
        confidence="declared",
    ))
    db.commit()

    out = call_mcp_tool(db, "describe_cli", {"slug": "secret-cli"})
    assert "content" in out
    block = out["content"][0]
    assert block["type"] == "json"
    payload = block["json"]
    # launch_spec must be absent from the MCP response (default/unauthenticated path)
    assert "launch_spec" not in payload
    # sanity: we got a real describe result, not an error
    assert "error" not in payload
    assert payload.get("slug") == "secret-cli"
