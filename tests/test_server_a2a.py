import json
import jsonschema
from fastapi.testclient import TestClient
from core.cardgen.card import build_agent_card
from core.server.app import create_app

_TOKEN = "test-secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def test_agent_card_validates_v1(db):
    card = build_agent_card("http://localhost:8080")
    schema = json.load(open("tests/fixtures/a2a_agent_card_v1.0.schema.json"))
    jsonschema.validate(card, schema)
    assert card["capabilities"]["pushNotifications"] is False
    assert "plan-cli-chain" in [s["id"] for s in card["skills"]]


def test_a2a_sendmessage_returns_catalog_not_execution(db, spawn_spy, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog", "input": {"query": ""}}},
        headers=_AUTH)
    assert resp.status_code == 200
    assert spawn_spy == []                       # describe-only: no CLI spawned


# ---------------------------------------------------------------------------
# Authentication enforcement tests
# ---------------------------------------------------------------------------

def test_unauth_wrong_token_rejected_401(db, monkeypatch):
    """Wrong bearer token → 401 on a protected endpoint."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/clis", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401

    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog", "input": {"query": ""}}},
        headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_unauth_missing_header_rejected(db, monkeypatch):
    """Missing Authorization header → 401 (actual behavior in this FastAPI/httpx version).
    Note: docs say HTTPBearer auto_error=True returns 403 on missing header, but the
    starlette TestClient here returns 401. Pinned to observed behavior."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/clis")
    # Observed: 401 (not 403) — missing header treated same as wrong token
    assert resp.status_code in (401, 403)


def test_authed_request_allowed(db, monkeypatch):
    """Correct bearer token → 200 on GET /clis."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app)
    resp = client.get("/clis", headers=_AUTH)
    assert resp.status_code == 200


def test_public_endpoints_need_no_auth(db):
    """/.well-known/agent-card.json and /health are reachable without auth."""
    app = create_app(db)
    client = TestClient(app)
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200

    resp = client.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------

def test_a2a_unknown_input_key_returns_structured_error(db, monkeypatch):
    """Unknown input keys return {"error": ...} — not a 500."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog",
                   "input": {"query": "", "unexpected_key": "boom"}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "unknown input keys" in body["error"]


def test_a2a_missing_required_input_key_returns_structured_error(db, monkeypatch):
    """Missing required keys (slug for describe-cli) return {"error": ...} — not a 500."""
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(db)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "describe-cli", "input": {}}},
        headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "missing required input keys" in body["error"]
