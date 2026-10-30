from dataclasses import dataclass
from typing import Callable
from core.catalog import queries
from core.playbooks import queries as playbook_queries
from core.playbooks import resolve as playbook_resolve


@dataclass(frozen=True)
class Op:
    canonical_id: str                  # snake_case
    handler: Callable
    input_schema: dict                 # JSON schema; every property carries a description
    description: str                   # one-sentence capability text advertised on MCP/A2A

    @property
    def a2a_skill(self) -> str:        # kebab-case
        return self.canonical_id.replace("_", "-")

    @property
    def mcp_tool(self) -> str:         # snake_case (== canonical)
        return self.canonical_id


def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _str_array(desc: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": desc}


# Descriptions are what an MCP client's tool search matches on. Hermes
# tool_search (auto mode) saw 'Registry op: <name>' here and never called the
# registry (0 calls in 14 days, measured 2026-10-31); US-CLIREG-HERMES-DISCOVERY-01.
OPS = [
    Op("search_cli_catalog", queries.search_clis,
       {"type": "object", "properties": {
           "query": _str("Free-text search terms taken from the goal (e.g. 'pdf text', "
                         "'git status'); an empty string lists the whole catalog.")}},
       "Find command-line tools in the operator's local fleet catalog by free-text "
       "query over slug, description and capability tags; returns matching CLIs with "
       "their health status. Start here for any 'which tool can do X' question."),
    Op("describe_cli", queries.describe_cli,
       {"type": "object",
        "properties": {
            "slug": _str("The CLI's catalog slug, as returned by search_cli_catalog."),
            "include_launch_spec": {
                "type": "boolean",
                "description": "Also return the launch spec (interpreter kind, entrypoint, "
                               "script path, args schema) needed to run the CLI."}},
        "required": ["slug"]},
       "Describe one catalog CLI by slug: purpose, capability (intent tags, typed "
       "inputs and outputs, side effects), current health, and optionally how to "
       "launch it."),
    Op("get_cli_health", queries.cli_health,
       {"type": "object",
        "properties": {"slug": _str("The CLI's catalog slug.")},
        "required": ["slug"]},
       "Return the last health probe result for one catalog CLI (healthy, unhealthy, "
       "unknown, stale or not_standalone) and the time it was checked."),
    Op("get_cli_graph", queries.cli_graph,
       {"type": "object", "properties": {}},
       "Return the typed chaining graph of the catalog: which CLI outputs can feed "
       "which CLI inputs, for reasoning about multi-step pipelines before planning one."),
    Op("plan_cli_chain", queries.plan_cli_chain,
       {"type": "object", "properties": {
           "goal_inputs": _str_array("Typed ports you already have, from the registered "
                                     "vocabulary (e.g. 'file:pdf'); empty when starting "
                                     "from nothing."),
           "goal_outputs": _str_array("Typed ports you want to end with (e.g. 'text:doc')."),
           "allow_side_effects": _str_array("Side-effect classes the chain may use "
                                            "(writes-fs, network, external, email); "
                                            "omit to allow none."),
           "goal_actions": _str_array("Intent verbs the chain must perform "
                                      "(e.g. 'convert', 'summarize')."),
           "producer_terms": _str_array("Words every first-hop producer must declare "
                                        "(e.g. 'git', 'status'); goals with unrelated "
                                        "terms fail cleanly instead of guessing.")},
        "required": ["goal_inputs", "goal_outputs"]},
       "Plan a chain of healthy catalog CLIs that turns the given input types into the "
       "goal output types; returns ranked chains, or none when no healthy producer "
       "exists for the goal."),
    Op("list_playbooks", playbook_queries.list_playbooks,
       {"type": "object", "properties": {
           "query": _str("Optional free-text filter over playbook names and purposes; "
                         "empty lists all playbooks.")}},
       "List the saved multi-step playbooks (named CLI recipes with fixed steps), "
       "optionally filtered by a free-text query."),
    Op("suggest_playbook", playbook_queries.suggest_playbook,
       {"type": "object",
        "properties": {
            "goal": _str("The task in plain language."),
            "limit": {"type": "integer",
                      "description": "Maximum number of suggestions to return (default 3)."}},
        "required": ["goal"]},
       "Rank the saved playbooks against a plain-language goal and return the best "
       "matching ones with their scores."),
    Op("resolve_playbook", playbook_resolve.resolve_playbook,
       {"type": "object",
        "properties": {"slug": _str("The playbook slug from list_playbooks or "
                                    "suggest_playbook.")},
        "required": ["slug"]},
       "Resolve one saved playbook by slug into its concrete steps against the live "
       "catalog, so each step names a currently registered CLI."),
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
