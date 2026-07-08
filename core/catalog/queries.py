# core/catalog/queries.py
from sqlmodel import select, text
from core.models import Cli, Capability, CliEdge
from core.health import norm_health as _norm_health  # shared vocabulary (single source of truth)
from core.planner.search import plan_chain as _plan


def _sanity_columns_present(session) -> bool:
    """sanity_ok/sanity_reason/sanity_checked_at are drift-only columns (same
    pattern as provenance/description_provenance) added by
    tools.backfill_capabilities.ensure_provenance_columns via guarded ALTER,
    NOT declared on core.models.Capability. A DB that hasn't run the backfill
    yet (or the in-memory test schema) won't have them -- guard the raw-SQL
    read so callers still get a clean "never checked" (None) result."""
    rows = session.exec(text("PRAGMA table_info(capability)")).all()
    cols = {r[1] for r in rows}
    return {"sanity_ok", "sanity_reason", "sanity_checked_at"} <= cols


def _sanity_by_slug(session) -> dict:
    if not _sanity_columns_present(session):
        return {}
    rows = session.exec(
        text("SELECT cli_slug, sanity_ok, sanity_reason, sanity_checked_at FROM capability")
    ).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _cap_row(c, sanity=None):
    sanity_ok, sanity_reason, sanity_checked_at = sanity if sanity is not None else (None, None, None)
    return {"intent_tags": c.intent_tags.split(",") if c.intent_tags else [],
            "input_types": c.input_types.split(",") if c.input_types else [],
            "output_types": c.output_types.split(",") if c.output_types else [],
            "side_effect": c.side_effect, "confidence": c.confidence,
            "sanity_ok": bool(sanity_ok) if sanity_ok is not None else None,
            "sanity_reason": sanity_reason or "",
            "sanity_checked_at": sanity_checked_at}


def _caps(session, slug):
    rows = session.exec(select(Capability).where(Capability.cli_slug == slug)).all()
    sanity_by_slug = _sanity_by_slug(session)
    return [_cap_row(c, sanity_by_slug.get(c.cli_slug)) for c in rows]


def overview_rows(session):
    clis = session.exec(select(Cli)).all()
    caps = session.exec(select(Capability)).all()
    edges = session.exec(select(CliEdge)).all()
    sanity_by_slug = _sanity_by_slug(session)

    caps_by_slug = {}
    for cap in caps:
        caps_by_slug.setdefault(cap.cli_slug, []).append(_cap_row(cap, sanity_by_slug.get(cap.cli_slug)))

    return {
        "clis": [
            {"slug": c.slug, "lang": c.lang, "project": c.project,
             "description": c.description, "health_status": _norm_health(c.health_status)}
            for c in clis
        ],
        "caps_by_slug": caps_by_slug,
        "edges": [
            {"from": e.from_slug, "to": e.to_slug, "via_type": e.via_type}
            for e in edges
        ],
    }


def search_clis(session, query: str = ""):
    rows = session.exec(select(Cli)).all()
    q = query.lower()
    return [{"slug": c.slug, "lang": c.lang, "description": c.description,
             "health_status": _norm_health(c.health_status)}
            for c in rows if q in (c.slug + " " + c.description).lower()]


def describe_cli(session, slug: str, include_launch_spec: bool = False):
    c = session.get(Cli, slug)
    if c is None:
        return None
    out = {"slug": c.slug, "lang": c.lang, "description": c.description,
           "health_status": _norm_health(c.health_status), "capabilities": _caps(session, slug)}
    if include_launch_spec:
        out["launch_spec"] = c.launch_spec
    return out


def cli_health(session, slug: str):
    c = session.get(Cli, slug)
    if c is None:
        return {"slug": slug, "health_status": "unknown"}
    return {"slug": slug, "health_status": _norm_health(c.health_status),
            "checked_at": c.health_checked_at}


def cli_graph(session):
    return [{"from": e.from_slug, "to": e.to_slug, "via_type": e.via_type}
            for e in session.exec(select(CliEdge)).all()]


def export_rows(session):
    """Full, deterministically-ordered rows for OKF export.

    Unlike overview_rows/describe_cli this carries `path` and `updated_at`
    (needed for OKF `resource`/`timestamp`) and a fully sorted shape so the
    producer can emit byte-stable bundles. Fails loudly if a CLI has >1
    capability row (OKF v1 exports the one-capability-per-CLI invariant).
    """
    clis = session.exec(select(Cli)).all()
    caps_by_slug = {}
    for cap in session.exec(select(Capability)).all():
        caps_by_slug.setdefault(cap.cli_slug, []).append(cap)
    edges_by_slug = {}
    for e in session.exec(select(CliEdge)).all():
        edges_by_slug.setdefault(e.from_slug, []).append(e)

    out = []
    for c in sorted(clis, key=lambda x: ((x.project or ""), x.slug)):
        caps = caps_by_slug.get(c.slug, [])
        if len(caps) > 1:
            raise ValueError(
                f"OKF export: CLI {c.slug!r} has {len(caps)} capability rows; "
                "v1 exports one capability per CLI")
        cap = caps[0] if caps else None
        capability = None
        if cap is not None:
            capability = {
                "intent_tags": sorted(t for t in cap.intent_tags.split(",") if t),
                "input_types": sorted(t for t in cap.input_types.split(",") if t),
                "output_types": sorted(t for t in cap.output_types.split(",") if t),
                "side_effect": cap.side_effect,
                "confidence": cap.confidence,
            }
        edges = sorted(
            ({"to": e.to_slug, "via": e.via_type} for e in edges_by_slug.get(c.slug, [])),
            key=lambda d: (d["to"], d["via"]),
        )
        out.append({
            "slug": c.slug, "lang": c.lang, "project": c.project, "path": c.path,
            "updated_at": c.updated_at, "description": c.description or "",  # normalise NULL -> "" for OKF consumers
            "health_status": _norm_health(c.health_status),
            "capability": capability, "edges": edges,
        })
    return out


def plan_cli_chain(session, goal_inputs, goal_outputs, allow_side_effects=None):
    chains = _plan(session, goal_inputs, goal_outputs, allow_side_effects or [])
    health_by_slug = {}

    def _health(slug):
        if slug not in health_by_slug:
            c = session.get(Cli, slug)
            health_by_slug[slug] = _norm_health(c.health_status) if c else "unknown"
        return health_by_slug[slug]

    out = []
    for ch in chains:
        hops = [{**hop, "health_status": _health(hop["slug"])} for hop in ch.hops]
        out.append({"slugs": ch.slugs, "length": ch.length,
                    "side_effect_count": ch.side_effect_count, "hops": hops})
    return out
