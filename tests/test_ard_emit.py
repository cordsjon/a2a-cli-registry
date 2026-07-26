import json
import shlex

import pytest

from core.ard.emit import emit, EMIT_FORMATS


ENDPOINT = "http://reg:9113/mcp"


def test_claude_emit_has_bearer_header_and_roundtrips_shlex():
    out = emit("claude", ENDPOINT)
    # AC-2.4: header present, env-var by NAME (consumer-side expansion)
    assert '--header "Authorization: Bearer ${A2A_BEARER_TOKEN}"' in out
    assert shlex.split(out)  # parses cleanly as shell words
    assert out.startswith("claude mcp add --transport http cli-registry ")


def test_openworker_emit_is_json_with_secretstore_ref():
    doc = json.loads(emit("openworker", ENDPOINT))
    assert doc == {"name": "cli-registry", "transport": "http",
                   "url": ENDPOINT, "auth": "secretstore:cli-registry"}


def test_hermes_emit_is_config_line():
    assert emit("hermes", ENDPOINT) == f"cli_registry_url={ENDPOINT}"


def test_no_emit_format_ever_contains_a_token_literal(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "sk-SUPERSECRET")
    for fmt in EMIT_FORMATS:
        assert "sk-SUPERSECRET" not in emit(fmt, ENDPOINT)


def test_shell_metacharacters_in_endpoint_are_quoted():
    evil = "http://reg:9113/mcp$(rm -rf ~)"
    out = emit("claude", evil)
    # AC-2.5: the url must arrive as ONE inert shell word
    assert any(w == evil for w in shlex.split(out))


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        emit("gemini", ENDPOINT)
