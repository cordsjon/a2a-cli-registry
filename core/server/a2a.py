from core.ops_registry import OPS

_BY_SKILL = {o.a2a_skill: o for o in OPS}


def handle_a2a(session, method: str, params: dict):
    if method == "SendMessage":
        op = _BY_SKILL.get(params.get("skill"))
        if op is None:
            return {"error": "unknown skill"}
        result = op.handler(session, **params.get("input", {}))
        return {"result": result}            # data only; never executes a CLI
    if method == "GetTask":
        return {"status": "completed"}
    return {"error": "unknown method"}
