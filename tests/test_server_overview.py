from fastapi.testclient import TestClient

from core.models import Cli, Capability, CliEdge
from core.server.app import create_app


def test_overview_returns_html_with_seeded_slug_bucket_and_totals(db, app_session_factory):
    db.add(Cli(slug="alpha-cli", lang="python", project="alpha",
               description="alpha description", health_status="healthy"))
    db.add(Capability(cli_slug="alpha-cli", intent_tags="inspect",
                      input_types="file:json", output_types="text:plain"))
    db.add(CliEdge(from_slug="alpha-cli", to_slug="alpha-cli", via_type="text:plain"))
    db.commit()
    app = create_app(app_session_factory)

    with TestClient(app) as client:
        resp = client.get("/overview")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "alpha-cli" in resp.text
    assert "alpha" in resp.text
    assert "Total" in resp.text
    assert "1" in resp.text


def test_overview_empty_db_notice(app_session_factory):
    app = create_app(app_session_factory)

    with TestClient(app) as client:
        resp = client.get("/overview")

    assert resp.status_code == 200
    assert "empty" in resp.text
    assert "populate" in resp.text


def test_overview_is_open_when_bearer_token_is_set(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "secret")
    app = create_app(app_session_factory)

    with TestClient(app) as client:
        overview = client.get("/overview")
        clis = client.get("/clis")

    assert overview.status_code == 200
    assert clis.status_code in (401, 403)


def test_overview_renderer_failure_returns_500(app_session_factory, monkeypatch):
    from core.web import render as overview_render

    def _boom(_model):
        raise RuntimeError("template failed")

    monkeypatch.setattr(overview_render, "render_overview_html", _boom)
    app = create_app(app_session_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/overview")

    assert resp.status_code == 500
