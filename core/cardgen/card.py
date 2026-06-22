from core.ops_registry import OPS


def build_agent_card(base_url: str) -> dict:
    return {
        "protocolVersion": "1.0",
        "name": "a2a-cli-registry",
        "description": "Capability-typed catalog of local CLIs (describe + plan only).",
        "url": base_url,
        "capabilities": {"pushNotifications": False,
                         "extensions": [{"uri": "x-webhook-bus/v1"}]},
        "securityScheme": {"type": "http", "scheme": "bearer"},
        "skills": [{"id": o.a2a_skill, "description": o.canonical_id} for o in OPS],
    }
