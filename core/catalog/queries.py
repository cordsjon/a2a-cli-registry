# core/catalog/queries.py
from sqlmodel import select
from core.models import Cli, Capability, CliEdge
from core.planner.search import plan_chain as _plan


def _caps(session, slug):
    rows = session.exec(select(Capability).where(Capability.cli_slug == slug)).all()
    return [{"intent_tags": c.intent_tags.split(",") if c.intent_tags else [],
             "input_types": c.input_types.split(",") if c.input_types else [],
             "output_types": c.output_types.split(",") if c.output_types else [],
             "side_effect": c.side_effect, "confidence": c.confidence} for c in rows]


def search_clis(session, query: str = ""):
    rows = session.exec(select(Cli)).all()
    q = query.lower()
    return [{"slug": c.slug, "lang": c.lang, "description": c.description,
             "health_status": c.health_status}
            for c in rows if q in (c.slug + " " + c.description).lower()]


def describe_cli(session, slug: str, include_launch_spec: bool = False):
    c = session.get(Cli, slug)
    if c is None:
        return None
    out = {"slug": c.slug, "lang": c.lang, "description": c.description,
           "health_status": c.health_status, "capabilities": _caps(session, slug)}
    if include_launch_spec:
        out["launch_spec"] = c.launch_spec
    return out


def cli_health(session, slug: str):
    c = session.get(Cli, slug)
    if c is None:
        return {"slug": slug, "health_status": "UNKNOWN"}
    return {"slug": slug, "health_status": c.health_status,
            "checked_at": c.health_checked_at}


def cli_graph(session):
    return [{"from": e.from_slug, "to": e.to_slug, "via_type": e.via_type}
            for e in session.exec(select(CliEdge)).all()]


def plan_cli_chain(session, goal_inputs, goal_outputs, allow_side_effects=None):
    chains = _plan(session, goal_inputs, goal_outputs, allow_side_effects or [])
    return [{"slugs": ch.slugs, "length": ch.length,
             "side_effect_count": ch.side_effect_count, "hops": ch.hops} for ch in chains]
