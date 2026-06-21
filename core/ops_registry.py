from dataclasses import dataclass
from typing import Callable
from core.catalog import queries


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
       {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]}),
    Op("get_cli_health", queries.cli_health,
       {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]}),
    Op("get_cli_graph", queries.cli_graph,
       {"type": "object", "properties": {}}),
    Op("plan_cli_chain", queries.plan_cli_chain,
       {"type": "object", "properties": {
           "goal_inputs": _STR_ARRAY, "goal_outputs": _STR_ARRAY,
           "allow_side_effects": _STR_ARRAY},
        "required": ["goal_inputs", "goal_outputs"]}),
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
