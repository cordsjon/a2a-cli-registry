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


def test_mcp_wrong_type_arg_returns_structured_error(db):
    """Wrong-type arg (int instead of list for goal_inputs) is now caught by schema
    type validation BEFORE the handler runs — returns a structured error block
    mentioning the type problem."""
    out = call_mcp_tool(db, "plan_cli_chain", {"goal_inputs": 42, "goal_outputs": ["text"]})
    assert "content" in out
    block = out["content"][0]
    assert block["type"] == "json"
    error_msg = block["json"].get("error", "")
    assert error_msg, f"expected error key, got: {block['json']}"
    # tightened: must mention the field name and the type problem
    assert "goal_inputs" in error_msg, f"error should mention field name: {error_msg}"
    assert "array" in error_msg or "int" in error_msg, (
        f"error should mention type info: {error_msg}"
    )


def test_wrong_type_arg_rejected(db):
    """search_cli_catalog with query=123 (int instead of str) is rejected by schema
    validation and returns a structured error — NOT a success and NOT an uncaught exception."""
    out = call_mcp_tool(db, "search_cli_catalog", {"query": 123})
    assert "content" in out
    block = out["content"][0]
    assert block["type"] == "json"
    error_msg = block["json"].get("error", "")
    assert error_msg, f"expected error, got success: {block['json']}"
    assert "query" in error_msg
    assert "string" in error_msg or "int" in error_msg


def test_correct_type_arg_accepted(db):
    """search_cli_catalog with query as a proper string succeeds (no error key)."""
    out = call_mcp_tool(db, "search_cli_catalog", {"query": "ripgrep"})
    assert "content" in out
    block = out["content"][0]
    assert block["type"] == "json"
    assert "error" not in block["json"], f"unexpected error: {block['json']}"


def test_array_wrong_type_rejected(db):
    """plan_cli_chain with goal_inputs as a string (not array) is rejected.
    Covers array-vs-string type mismatch since no op has an integer field."""
    out = call_mcp_tool(db, "plan_cli_chain", {"goal_inputs": "notalist", "goal_outputs": ["text"]})
    assert "content" in out
    block = out["content"][0]
    assert block["type"] == "json"
    error_msg = block["json"].get("error", "")
    assert error_msg, f"expected error for string-as-array, got: {block['json']}"
    assert "goal_inputs" in error_msg
    assert "array" in error_msg or "str" in error_msg


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


def test_plan_cli_chain_accepts_goal_actions_key(db):
    # schema omission guard (§3): without the ops-schema entry this returns
    # "unknown input keys: ['goal_actions']" (ops_registry.py:101)
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": [], "goal_outputs": ["text"], "goal_actions": []})
    payload = out["content"][0]["json"]
    assert not (isinstance(payload, dict) and "unknown input keys" in str(payload.get("error", "")))


def test_plan_cli_chain_unknown_verb_is_structured_error(db):
    # §2.8: unknown verb -> structured op error with the known-verbs vocabulary
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": [], "goal_outputs": [], "goal_actions": ["telegram"]})
    err = out["content"][0]["json"]["error"]
    assert "unknown action verb: telegram" in err and "known:" in err


def test_plan_cli_chain_multi_match_integrity_error_is_structured(db):
    # registry half of §5 test (n): the §2.2 integrity ValueError surfaces as a
    # structured _error_block, not an unstructured exception
    db.add(Cli(slug="dual_mail", lang="python"))
    db.add(Capability(cli_slug="dual_mail", intent_tags="notify,send", input_types="text",
                      output_types="text", side_effect="external", confidence="declared"))
    db.commit()
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": [], "goal_outputs": [], "goal_actions": ["email"]})
    err = out["content"][0]["json"]["error"]
    assert "action verb integrity" in err and "dual_mail" in err
