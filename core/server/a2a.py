from core.ops_registry import OPS, validate_input as _validate_input_shared

_BY_SKILL = {o.a2a_skill: o for o in OPS}


def _validate_input(op, input_dict: dict):
    """Validate input keys and types against op.input_schema. Returns error string or None."""
    return _validate_input_shared(op, input_dict)


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
