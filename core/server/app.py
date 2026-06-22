import contextlib
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
    from core.mcp.http import build_mcp_app, _bearer_gate

    # Build the MCP sub-app before constructing FastAPI so its lifespan context
    # can be wired into the parent app.  FastMCP's StreamableHTTPSessionManager
    # must be started via session_manager.run() (exposed as the sub-app's
    # router.lifespan_context) before any request reaches the handler — mounting
    # the sub-app alone is not enough because FastAPI never propagates a mounted
    # child's lifespan.
    mcp_app = build_mcp_app(session)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(lifespan=lifespan)

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

    app.mount("/mcp", _bearer_gate(mcp_app))

    return app
