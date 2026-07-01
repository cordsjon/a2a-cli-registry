from core.ops_registry import op_by_a2a_skill, op_by_mcp_tool, validate_input


def test_suggest_playbook_op_registered():
    op = op_by_a2a_skill("suggest-playbook")
    assert op.mcp_tool == "suggest_playbook"
    # required "goal" enforced by shared validator
    assert validate_input(op, {}) == "missing required input keys: ['goal']"
    assert validate_input(op, {"goal": "x"}) is None


def test_list_playbooks_op_registered():
    op = op_by_mcp_tool("list_playbooks")
    assert op.a2a_skill == "list-playbooks"
    assert validate_input(op, {"query": "etsy"}) is None
    assert validate_input(op, {"bogus": 1}) == "unknown input keys: ['bogus']"
