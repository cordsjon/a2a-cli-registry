import json
import jsonschema
from fastapi.testclient import TestClient
from core.cardgen.card import build_agent_card
from core.server.app import create_app


def test_agent_card_validates_v1(db):
    card = build_agent_card("http://localhost:8080")
    schema = json.load(open("tests/fixtures/a2a_agent_card_v1.0.schema.json"))
    jsonschema.validate(card, schema)
    assert card["capabilities"]["pushNotifications"] is False
    assert "plan-cli-chain" in [s["id"] for s in card["skills"]]


def test_a2a_sendmessage_returns_catalog_not_execution(db, spawn_spy):
    app = create_app(db)
    client = TestClient(app)
    resp = client.post("/a2a", json={"method": "SendMessage",
        "params": {"skill": "search-cli-catalog", "input": {"query": ""}}})
    assert resp.status_code == 200
    assert spawn_spy == []                       # describe-only: no CLI spawned
