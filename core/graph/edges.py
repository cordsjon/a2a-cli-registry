# core/graph/edges.py
from sqlmodel import select
from core.models import Capability, CliEdge

_HUB_TYPES = {"text", "json"}   # bare hubs need a shared intent_tag to form an edge


def _caps(session):
    rows = session.exec(select(Capability)).all()
    out = {}
    for c in rows:
        out.setdefault(c.cli_slug, []).append(c)
    return out


def _desired_edges(session, vocab) -> set[tuple[str, str, str]]:
    caps = _caps(session)
    edges = set()
    for from_slug, from_caps in caps.items():
        out_ports = {p.strip() for c in from_caps for p in c.output_types.split(",") if p.strip()}
        from_tags = {t.strip() for c in from_caps for t in c.intent_tags.split(",") if t.strip()}
        for to_slug, to_caps in caps.items():
            if to_slug == from_slug:
                continue
            in_ports = {p.strip() for c in to_caps for p in c.input_types.split(",") if p.strip()}
            to_tags = {t.strip() for c in to_caps for t in c.intent_tags.split(",") if t.strip()}
            for via in out_ports & in_ports:
                if not vocab.is_edge_eligible(via):
                    continue                      # unregistered/unverified excluded
                if via in _HUB_TYPES and not (from_tags & to_tags):
                    continue                      # hub-type down-weight
                edges.add((from_slug, to_slug, via))
    return edges


def current_edges(session) -> set[tuple[str, str, str]]:
    return {(e.from_slug, e.to_slug, e.via_type) for e in session.exec(select(CliEdge)).all()}


def compute_edges(session, vocab, clock, changed_slugs=None) -> list:
    """Recompute edges. Atomic shadow-swap within one transaction; returns the
    delta of (from,to,via_type) tuples (added union removed). Empty list = no-op."""
    desired = _desired_edges(session, vocab)
    existing = current_edges(session)
    if changed_slugs is not None:
        # incremental: only consider edges where a changed slug is an endpoint
        desired = (
            {e for e in desired if e[0] in changed_slugs or e[1] in changed_slugs}
            | {e for e in existing if e[0] not in changed_slugs and e[1] not in changed_slugs}
        )
    if desired == existing:
        return []                                  # no-op emits nothing
    # shadow-swap: delete all, insert desired, single transaction
    for e in session.exec(select(CliEdge)).all():
        session.delete(e)
    for (f, t, v) in desired:
        session.add(CliEdge(from_slug=f, to_slug=t, via_type=v, recomputed_at=clock.now()))
    session.commit()
    delta = (desired - existing) | (existing - desired)
    return sorted(delta)
