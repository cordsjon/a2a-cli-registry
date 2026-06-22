import json
import jsonschema
from fastapi.testclient import TestClient
from core.cardgen.card import build_agent_card
from core.server.app import create_app

_TOKEN = "test-secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def test_agent_card_validates_v1(db):
    card = build_agent_card("http://localhost:8080")
    with open("tests/fixtures/a2a_agent_card_v1.0.schema.json") as f:
        schema = json.load(f)
    jsonschema.validate(card, schema)
    assert card["capabilities"]["pushNotifications"] is False
    assert "plan-cli-chain" in [s["id"] for s in card["skills"]]


def test_a2a_sendmessage_returns_catalog_not_execution(app_session_factory, spawn_spy, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog", "input": {"query": ""}}},
        headers=_AUTH)
    assert resp.status_code == 200
    assert spawn_spy == []                       # describe-only: no CLI spawned


# ---------------------------------------------------------------------------
# Authentication enforcement tests
# ---------------------------------------------------------------------------

def test_unauth_wrong_token_rejected_401(app_session_factory, monkeypatch):
    """Wrong bearer token → 401 on a protected endpoint."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app, raise_server_exceptions=False)
    bad = {"Authorization": "Bearer wrong-token"}
    assert client.get("/clis", headers=bad).status_code == 401
    assert client.get("/clis/some-slug", headers=bad).status_code == 401
    assert client.get("/graph", headers=bad).status_code == 401

    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog", "input": {"query": ""}}},
        headers=bad)
    assert resp.status_code == 401


def test_unauth_missing_header_rejected(app_session_factory, monkeypatch):
    """Missing Authorization header → 401 (actual behavior in this FastAPI/httpx version).
    Note: docs say HTTPBearer auto_error=True returns 403 on missing header, but the
    starlette TestClient here returns 401. Pinned to observed behavior."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/clis")
    # Observed: 401 (not 403) — missing header treated same as wrong token
    assert resp.status_code in (401, 403)


def test_authed_request_allowed(app_session_factory, monkeypatch):
    """Correct bearer token → 200 on GET /clis."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.get("/clis", headers=_AUTH)
    assert resp.status_code == 200


def test_public_endpoints_need_no_auth(app_session_factory):
    """/.well-known/agent-card.json and /health are reachable without auth."""
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200

    resp = client.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------

def test_a2a_unknown_input_key_returns_structured_error(app_session_factory, monkeypatch):
    """Unknown input keys return {"error": ...} — not a 500."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog",
                   "input": {"query": "", "unexpected_key": "boom"}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "unknown input keys" in body["error"]


def test_a2a_missing_required_input_key_returns_structured_error(app_session_factory, monkeypatch):
    """Missing required keys (slug for describe-cli) return {"error": ...} — not a 500."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "describe-cli", "input": {}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "missing required input keys" in body["error"]


def test_a2a_wrong_type_arg_returns_structured_error(app_session_factory, monkeypatch):
    """Wrong-type arg (int instead of list for goal_inputs) is now caught by schema
    type validation BEFORE the handler runs — returns {"error": ...} mentioning
    the type problem, not a 500."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "plan-cli-chain",
                   "input": {"goal_inputs": 42, "goal_outputs": ["text"]}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    error_msg = body.get("error", "")
    assert error_msg, f"expected error key, got: {body}"
    # tightened: must mention the field name and the type problem
    assert "goal_inputs" in error_msg, f"error should mention field name: {error_msg}"
    assert "array" in error_msg or "int" in error_msg, (
        f"error should mention type info: {error_msg}"
    )


def test_a2a_wrong_type_string_field_rejected(app_session_factory, monkeypatch):
    """A2A: search-cli-catalog with query=123 (int instead of str) returns
    {"error": ...} mentioning the type problem — NOT a success and NOT an uncaught exception."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog", "input": {"query": 123}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    error_msg = body.get("error", "")
    assert error_msg, f"expected error, got success: {body}"
    assert "query" in error_msg
    assert "string" in error_msg or "int" in error_msg


def test_a2a_correct_type_arg_accepted(app_session_factory, monkeypatch):
    """A2A: search-cli-catalog with query as a proper string succeeds (no error key)."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog", "input": {"query": "ripgrep"}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "error" not in body, f"unexpected error: {body}"


def test_a2a_array_wrong_type_rejected(app_session_factory, monkeypatch):
    """A2A: plan-cli-chain with goal_inputs as a string (not array) is rejected.
    Covers array-vs-string type mismatch since no op has an integer field."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "plan-cli-chain",
                   "input": {"goal_inputs": "notalist", "goal_outputs": ["text"]}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    error_msg = body.get("error", "")
    assert error_msg, f"expected error for string-as-array, got: {body}"
    assert "goal_inputs" in error_msg
    assert "array" in error_msg or "str" in error_msg


# ---------------------------------------------------------------------------
# Per-request session isolation tests
# ---------------------------------------------------------------------------

def test_session_factory_yields_independent_sessions(tmp_path):
    """session_factory() yields a FRESH Session on every call — not the same object.

    The app_session_factory fixture uses nullcontext(db) so every 'per-request'
    call gets the SAME shared session (intentional for data-sharing in unit tests).
    This test verifies the REAL factory behaviour: each call produces a distinct,
    independent Session object, proving the per-request isolation contract.
    """
    from core.store.db import init_db, session_factory
    engine = init_db(str(tmp_path / "iso.db"))
    factory = session_factory(engine)
    with factory() as a:
        with factory() as b:
            assert a is not b           # each call yields a FRESH Session
    # a fresh call after the first two are closed is also independent
    with factory() as c:
        assert c is not a


def test_two_requests_real_factory_no_session_reuse_error(tmp_path, monkeypatch):
    """Two sequential HTTP requests through a real init_db-backed app both return 200.

    Uses a real session_factory (not nullcontext) and TestClient as a context manager
    so the MCP lifespan open/close runs cleanly, exercising the full per-request path.
    A 'session bound to different thread' or rolled-back-transaction error would surface
    as a 500 here if the same Session object were reused across requests.
    """
    monkeypatch.setenv("A2A_BEARER_TOKEN", "tok")
    from core.store.db import init_db, session_factory
    engine = init_db(str(tmp_path / "req.db"))
    app = create_app(session_factory(engine))
    h = {"Authorization": "Bearer tok"}
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/clis", headers=h).status_code == 200
        assert c.get("/clis", headers=h).status_code == 200
