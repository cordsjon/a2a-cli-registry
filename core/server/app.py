from fastapi import FastAPI
from core.cardgen.card import build_agent_card
from core.server.a2a import handle_a2a
from core.catalog import queries


def create_app(session):
    app = FastAPI()

    @app.get("/.well-known/agent-card.json")
    def card():
        return build_agent_card("http://localhost:8080")

    @app.get("/clis")
    def list_clis(query: str = ""):
        return queries.search_clis(session, query)

    @app.get("/clis/{slug}")
    def describe(slug: str):
        return queries.describe_cli(session, slug)

    @app.get("/graph")
    def graph():
        return queries.cli_graph(session)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/a2a")
    def a2a(body: dict):
        return handle_a2a(session, body.get("method"), body.get("params", {}))

    return app
