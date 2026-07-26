"""Consumer config emit (spec US-2). Never touches tokens: snippets reference
$A2A_BEARER_TOKEN / SecretStore entries by NAME only. Everything interpolated
into shell text is shlex-quoted (catalog content is untrusted)."""
import json
import shlex

EMIT_FORMATS = ("claude", "openworker", "hermes")


def emit(fmt: str, endpoint: str) -> str:
    if fmt == "claude":
        return (
            f"claude mcp add --transport http cli-registry {shlex.quote(endpoint)} "
            f'--header "Authorization: Bearer ${{A2A_BEARER_TOKEN}}"'
        )
    if fmt == "openworker":
        return json.dumps({
            "name": "cli-registry",
            "transport": "http",
            "url": endpoint,
            "auth": "secretstore:cli-registry",
        })
    if fmt == "hermes":
        return f"cli_registry_url={endpoint}"
    raise ValueError(f"unknown emit format '{fmt}' (choose: {', '.join(EMIT_FORMATS)})")
