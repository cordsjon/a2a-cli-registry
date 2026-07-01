from dataclasses import dataclass
from typing import Callable
from core.catalog import queries
from core.playbooks import queries as playbook_queries


@dataclass(frozen=True)
class Op:
    canonical_id: str                  # snake_case
    handler: Callable
    input_schema: dict

    @property
    def a2a_skill(self) -> str:        # kebab-case
        return self.canonical_id.replace("_", "-")

    @property
    def mcp_tool(self) -> str:         # snake_case (== canonical)
        return self.canonical_id


_STR_ARRAY = {"type": "array", "items": {"type": "string"}}

OPS = [
    Op("search_cli_catalog", queries.search_clis,
       {"type": "object", "properties": {"query": {"type": "string"}}}),
    Op("describe_cli", queries.describe_cli,
       {"type": "object",
        "properties": {"slug": {"type": "string"},
                       "include_launch_spec": {"type": "boolean"}},
        "required": ["slug"]}),
    Op("get_cli_health", queries.cli_health,
       {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]}),
    Op("get_cli_graph", queries.cli_graph,
       {"type": "object", "properties": {}}),
    Op("plan_cli_chain", queries.plan_cli_chain,
       {"type": "object", "properties": {
           "goal_inputs": _STR_ARRAY, "goal_outputs": _STR_ARRAY,
           "allow_side_effects": _STR_ARRAY},
        "required": ["goal_inputs", "goal_outputs"]}),
    Op("list_playbooks", playbook_queries.list_playbooks,
       {"type": "object", "properties": {"query": {"type": "string"}}}),
    Op("suggest_playbook", playbook_queries.suggest_playbook,
       {"type": "object",
        "properties": {"goal": {"type": "string"},
                       "limit": {"type": "integer"}},
        "required": ["goal"]}),
]


def a2a_skill_ids():
    return [o.a2a_skill for o in OPS]


def mcp_tool_ids():
    return [o.mcp_tool for o in OPS]


def op_by_mcp_tool(name: str) -> Op:
    for o in OPS:
        if o.mcp_tool == name:
            return o
    raise KeyError(name)


def op_by_a2a_skill(name: str) -> Op:
    for o in OPS:
        if o.a2a_skill == name:
            return o
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Shared input validator (used by both A2A and MCP surfaces)
# ---------------------------------------------------------------------------

_JSON_SCHEMA_TYPE_MAP: dict[str, type | tuple] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_input(op: "Op", arguments: dict) -> "str | None":
    """Validate *arguments* against op.input_schema: unknown keys, missing
    required keys, AND basic JSON-Schema type checks. Returns an error string
    or None if valid."""
    properties = op.input_schema.get("properties", {})
    allowed = set(properties.keys())
    required = set(op.input_schema.get("required", []))
    given = set(arguments.keys())

    unknown = given - allowed
    if unknown:
        return f"unknown input keys: {sorted(unknown)}"

    missing = required - given
    if missing:
        return f"missing required input keys: {sorted(missing)}"

    for key, value in arguments.items():
        prop_schema = properties.get(key, {})
        expected_type_name = prop_schema.get("type")
        if expected_type_name is None:
            continue  # no type constraint declared — skip
        python_type = _JSON_SCHEMA_TYPE_MAP.get(expected_type_name)
        if python_type is None:
            continue  # unknown JSON-schema type — skip
        # bool is a subclass of int in Python; reject it for "integer" and "number"
        if expected_type_name in ("integer", "number") and isinstance(value, bool):
            return (
                f"input '{key}' must be {expected_type_name}"
                f" (got {type(value).__name__})"
            )
        if not isinstance(value, python_type):
            return (
                f"input '{key}' must be {expected_type_name}"
                f" (got {type(value).__name__})"
            )

    return None
