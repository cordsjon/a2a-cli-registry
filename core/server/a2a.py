from core.ops_registry import OPS

_BY_SKILL = {o.a2a_skill: o for o in OPS}


def _validate_input(op, input_dict: dict):
    """Validate input keys against op.input_schema. Returns error string or None."""
    allowed = set(op.input_schema.get("properties", {}).keys())
    required = set(op.input_schema.get("required", []))
    given = set(input_dict.keys())

    unknown = given - allowed
    if unknown:
        return f"unknown input keys: {sorted(unknown)}"

    missing = required - given
    if missing:
        return f"missing required input keys: {sorted(missing)}"

    return None


def handle_a2a(session, method: str, params: dict):
    if method == "SendMessage":
        op = _BY_SKILL.get(params.get("skill"))
        if op is None:
            return {"error": "unknown skill"}
        input_dict = params.get("input", {})
        err = _validate_input(op, input_dict)
        if err:
            return {"error": err}
        try:
            result = op.handler(session, **input_dict)
        except (TypeError, ValueError) as exc:
            return {"error": f"invalid input: {exc}"}
        return {"result": result}            # data only; never executes a CLI
    if method == "GetTask":
        return {"status": "completed"}
    return {"error": "unknown method"}
