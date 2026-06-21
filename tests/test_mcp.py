import jsonschema
from core.mcp.server import build_mcp_tools, call_mcp_tool


def test_tool_schema_is_valid_jsonschema_input_only():
    tools = build_mcp_tools()
    plan = next(t for t in tools if t["name"] == "plan_cli_chain")
    jsonschema.Draft7Validator.check_schema(plan["inputSchema"])
    assert "outputSchema" not in plan            # output_types are NOT a tool output-schema


def test_result_is_structured_content_block(db, spawn_spy):
    out = call_mcp_tool(db, "search_cli_catalog", {"query": ""})
    assert out["content"][0]["type"] == "json"   # structured content, capability data inside
    assert spawn_spy == []                        # describe-only on MCP path too
