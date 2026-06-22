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


def create_app(session_factory, *, mcp_session=None):
    """Build the HTTP app.

    `session_factory` is a zero-arg callable returning a context-managed Session
    (see core.store.db.session_factory). REST/A2A routes open a FRESH session
    per request via the `_request_session` dependency — proper isolation rather
    than a single process-lifetime Session.

    The MCP sub-app cannot use FastAPI DI (it runs in FastMCP's own ASGI stack),
    so it keeps ONE stable build-time session for its lifespan: `mcp_session` if
    provided, otherwise one opened from the factory and closed on lifespan exit.
    """
    from core.mcp.http import build_mcp_app, mount_mcp

    def _request_session():
        with session_factory() as s:
            yield s

    # MCP needs a stable session for its lifespan. Use the supplied one, or open
    # a single build-time session from the factory and keep it for the MCP
    # sub-app's lifetime (closed when the parent app's lifespan ends).
    mcp_sess_cm = None
    if mcp_session is None:
        mcp_sess_cm = session_factory()
        # CONTRACT: this session is opened eagerly here and MUST be closed by the
        # lifespan's finally block below.  Callers must therefore run the app under
        # a lifespan-aware server (uvicorn) or use TestClient as a context manager
        # (`with TestClient(app) as c:`).  Building the app without running the
        # lifespan (e.g. plain `TestClient(app)` without entering it as a context
        # manager) will leave this one MCP session open — a harmless leak in tests
        # that use nullcontext, but a real resource leak against a real engine.
        mcp_session = mcp_sess_cm.__enter__()

    # Build the MCP sub-app before constructing FastAPI so its lifespan context
    # can be wired into the parent app.  FastMCP's StreamableHTTPSessionManager
    # must be started via session_manager.run() (exposed as the sub-app's
    # router.lifespan_context) before any request reaches the handler — mounting
    # the sub-app alone is not enough because FastAPI never propagates a mounted
    # child's lifespan.
    mcp_app = build_mcp_app(mcp_session)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            if mcp_sess_cm is not None:
                mcp_sess_cm.__exit__(None, None, None)

    app = FastAPI(lifespan=lifespan)

    @app.get("/.well-known/agent-card.json")
    def card():
        base_url = os.environ.get("A2A_BASE_URL", "http://localhost:8080")
        return build_agent_card(base_url)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/clis", dependencies=[Depends(_require_token)])
    def list_clis(query: str = "", session=Depends(_request_session)):
        return queries.search_clis(session, query)

    @app.get("/clis/{slug}", dependencies=[Depends(_require_token)])
    def describe(slug: str, session=Depends(_request_session)):
        return queries.describe_cli(session, slug)

    @app.get("/graph", dependencies=[Depends(_require_token)])
    def graph(session=Depends(_request_session)):
        return queries.cli_graph(session)

    @app.post("/a2a", dependencies=[Depends(_require_token)])
    def a2a(body: dict, session=Depends(_request_session)):
        return handle_a2a(session, body.get("method"), body.get("params", {}))

    mount_mcp(app, mcp_app)

    return app
