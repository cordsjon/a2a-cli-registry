from core.ops_registry import OPS, a2a_skill_ids, mcp_tool_ids, op_by_mcp_tool, op_by_a2a_skill


def test_a2a_and_mcp_share_one_registry():
    # same op set, just naming-transformed
    assert {o.canonical_id for o in OPS} == set(mcp_tool_ids())
    assert len(a2a_skill_ids()) == len(mcp_tool_ids()) == len(OPS)


def test_kebab_a2a_snake_mcp_transform():
    op = op_by_mcp_tool("plan_cli_chain")
    assert op.a2a_skill == "plan-cli-chain"
    assert op.mcp_tool == "plan_cli_chain"


def test_op_by_a2a_skill_round_trips():
    op = op_by_a2a_skill("plan-cli-chain")
    assert op.canonical_id == "plan_cli_chain"
    assert op.mcp_tool == "plan_cli_chain"


def test_every_op_has_input_schema():
    for o in OPS:
        assert o.input_schema["type"] == "object"


def test_every_op_and_parameter_carries_a_description():
    """US-CLIREG-HERMES-DISCOVERY-01 AC-01: the op table is the single source
    of the text MCP tools/list advertises; a thin or missing description here
    makes the tool invisible to description-matching tool search."""
    for o in OPS:
        assert len(o.description.split()) >= 8, o.canonical_id
        assert not o.description.startswith("Registry op"), o.canonical_id
        for pname, pschema in o.input_schema.get("properties", {}).items():
            assert pschema.get("description", "").strip(), f"{o.canonical_id}.{pname}"
