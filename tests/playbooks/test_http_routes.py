from fastapi.testclient import TestClient
from core.server.app import create_app

_TOKEN = "test-secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def test_playbooks_route_lists(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app)
    r = client.get("/playbooks", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "playbooks" in body


def test_playbook_detail_404(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/playbooks/does-not-exist", headers=_AUTH)
    assert r.status_code == 404


def test_playbooks_route_needs_auth(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    app = create_app(app_session_factory)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/playbooks", headers={"Authorization": "Bearer wrong"}).status_code == 401
