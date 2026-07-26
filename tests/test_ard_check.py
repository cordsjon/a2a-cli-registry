import contextlib
import http.server
import socket
import threading

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


def test_check_entry_with_no_url_fails_cleanly(monkeypatch, capsys):
    # the ARD schema allows a 'data' (inline) entry variant with no 'url' key —
    # that must FAIL that one entry, not crash run_check with a KeyError
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    catalog = {"specVersion": "1.0", "entries": [
        {"identifier": "urn:air:h:test:x", "type": "application/a2a-agent-card+json",
         "data": {"inline": True}},
    ]}
    monkeypatch.setattr(C, "fetch_json", _fetch(
        {"http://reg:9113/.well-known/ai-catalog.json": catalog}))
    rc = C.run_check("http://reg:9113")
    out = capsys.readouterr().out
    assert rc == 1
    assert "urn:air:h:test:x FAIL" in out
    assert "url" in out


# --- direct _endpoint_status coverage: real HTTP, nothing monkeypatched ---

@contextlib.contextmanager
def _server(status, body=b'{"jsonrpc":"2.0","id":1,"result":{}}'):
    """Local http.server answering POST with `status`. Yields the endpoint URL."""
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}/mcp"
    finally:
        srv.shutdown()
        srv.server_close()


def test_endpoint_status_auth_wrong_token_is_hard_fail():
    # a token was supplied and still got 401 -> the token is wrong: hard fail,
    # NOT the lenient alive-unverified tier
    with _server(401, b'{"error":"unauthorized"}') as ep:
        with pytest.raises(R.ArdError, match="HTTP 401"):
            C._endpoint_status(ep, "wrong-token")


def test_endpoint_status_unauth_401_is_alive_unverified():
    with _server(401, b'{"error":"unauthorized"}') as ep:
        assert C._endpoint_status(ep, None) == "alive-unverified"


def test_endpoint_status_auth_200_is_ok():
    with _server(200) as ep:
        assert C._endpoint_status(ep, "good-token") == "ok"


@contextlib.contextmanager
def _redirect_server(location=None, code=307, cross_origin_to=None):
    """POST /mcp -> 307 to /mcp/ (Starlette mount behaviour); POST /mcp/ -> 200.

    urllib does not auto-follow 307/308 on POST, so without an explicit follow
    in check.py this shape reads as a false FAIL against every real server.
    """
    body = b'{"jsonrpc":"2.0","id":1,"result":{}}'
    hits = {"slash": 0}

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            if self.path == "/mcp":
                self.send_response(code)
                self.send_header("Location", cross_origin_to or location or "/mcp/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            hits["slash"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}/mcp", hits
    finally:
        srv.shutdown()
        srv.server_close()


def test_endpoint_status_follows_same_origin_307_on_post():
    # regression: Starlette 307-redirects /mcp -> /mcp/, and urllib will NOT
    # follow that on POST. Before the follow-once fix this raised "HTTP 307".
    with _redirect_server() as (ep, hits):
        assert C._endpoint_status(ep, "good-token") == "ok"
        assert hits["slash"] == 1


def test_endpoint_status_refuses_cross_origin_redirect():
    # catalog/server-card content is untrusted: a redirect must never carry the
    # bearer token to another origin
    with _redirect_server(cross_origin_to="http://evil.example/mcp/") as (ep, hits):
        with pytest.raises(R.ArdError, match="HTTP 307"):
            C._endpoint_status(ep, "good-token")
        assert hits["slash"] == 0


def test_endpoint_status_redirect_loop_is_capped():
    # /mcp -> /mcp (self-redirect) must terminate, not recurse
    with _redirect_server(location="/mcp") as (ep, _hits):
        with pytest.raises(R.ArdError, match="HTTP 307"):
            C._endpoint_status(ep, "good-token")


def test_endpoint_status_unreachable_is_ard_error():
    # closed port -> URLError, surfaced as ArdError (never an uncaught OSError)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(R.ArdError, match="failed"):
        C._endpoint_status(f"http://127.0.0.1:{port}/mcp", "t")


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
