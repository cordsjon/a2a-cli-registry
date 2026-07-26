import pytest

import core.ard.check as C
import core.ard.resolve as R


CATALOG = {
    "specVersion": "1.0",
    "entries": [
        {"identifier": "urn:air:h:agent:catalog", "displayName": "a",
         "type": "application/a2a-agent-card+json",
         "url": "http://reg:9113/.well-known/agent-card.json"},
        {"identifier": "urn:air:h:mcp:server", "displayName": "m",
         "type": "application/mcp-server-card+json",
         "url": "http://reg:9113/.well-known/mcp-server-card.json"},
    ],
}
AGENT_CARD = {"protocolVersion": "1.0", "name": "a2a-cli-registry",
              "url": "http://reg:9113/a2a", "skills": []}
SERVER_CARD = {"name": "a2a-cli-registry", "endpoint": "http://reg:9113/mcp",
               "transport": "streamable-http", "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"}}


def _fetch(payloads):
    def f(url, deadline, max_bytes=1_048_576):
        v = payloads[url]
        if isinstance(v, Exception):
            raise v
        return v
    return f


def test_check_all_ok_unauthenticated(monkeypatch, capsys):
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(C, "fetch_json", _fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/agent-card.json": AGENT_CARD,
        "http://reg:9113/.well-known/mcp-server-card.json": SERVER_CARD,
    }))
    # unauthenticated tier: a 401 from the endpoint counts as alive-unverified
    monkeypatch.setattr(C, "_endpoint_status", lambda ep, token: "alive-unverified")
    rc = C.run_check("http://reg:9113")
    out = capsys.readouterr().out
    assert rc == 0
    assert "urn:air:h:agent:catalog ok" in out
    assert "urn:air:h:mcp:server alive-unverified" in out


def test_check_authenticated_handshake_reports_ok(monkeypatch, capsys):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "t")
    monkeypatch.setattr(C, "fetch_json", _fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/agent-card.json": AGENT_CARD,
        "http://reg:9113/.well-known/mcp-server-card.json": SERVER_CARD,
    }))
    monkeypatch.setattr(C, "_endpoint_status", lambda ep, token: "ok")
    assert C.run_check("http://reg:9113") == 0
    assert "urn:air:h:mcp:server ok" in capsys.readouterr().out


def test_check_dead_entry_fails_and_names_it(monkeypatch, capsys):
    # AC-7.2 red-first: a wrong entry url must FAIL the check and be named
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(C, "fetch_json", _fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/agent-card.json": R.ArdError("GET ... -> HTTP 404"),
        "http://reg:9113/.well-known/mcp-server-card.json": SERVER_CARD,
    }))
    monkeypatch.setattr(C, "_endpoint_status", lambda ep, token: "alive-unverified")
    rc = C.run_check("http://reg:9113")
    out = capsys.readouterr().out
    assert rc == 1
    assert "urn:air:h:agent:catalog FAIL" in out
