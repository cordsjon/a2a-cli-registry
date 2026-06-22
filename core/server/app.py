import os
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.cardgen.card import build_agent_card
from core.server.a2a import handle_a2a
from core.catalog import queries

_bearer = HTTPBearer(auto_error=True)


def _require_token(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    expected = os.environ.get("A2A_BEARER_TOKEN")
    if not expected or creds.credentials != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_app(session):
    app = FastAPI()

    @app.get("/.well-known/agent-card.json")
    def card():
        base_url = os.environ.get("A2A_BASE_URL", "http://localhost:8080")
        return build_agent_card(base_url)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/clis", dependencies=[Depends(_require_token)])
    def list_clis(query: str = ""):
        return queries.search_clis(session, query)

    @app.get("/clis/{slug}", dependencies=[Depends(_require_token)])
    def describe(slug: str):
        return queries.describe_cli(session, slug)

    @app.get("/graph", dependencies=[Depends(_require_token)])
    def graph():
        return queries.cli_graph(session)

    @app.post("/a2a", dependencies=[Depends(_require_token)])
    def a2a(body: dict):
        return handle_a2a(session, body.get("method"), body.get("params", {}))

    from core.mcp.http import mount_mcp
    mount_mcp(app, session)

    return app
