import json as _json
from sqlmodel import select
from core.models import Cli, Capability
from core.capability.model import CapabilityRecord, merge_capabilities, admit_ports
from core.graph.edges import compute_edges


class MassRemovalBreaker(RuntimeError):
    """>=threshold of existing CLIs would be removed — refuse, fail closed."""


def _adapter_for(rec, adapters):
    for a in adapters:
        if a.detect(rec):
            return a
    return None


def populate(session, source, adapters, vocab, clock, mass_removal_threshold=0.30):
    incoming = source.discover()                   # may raise SchemaError (fail closed)
    incoming_slugs = {r.slug for r in incoming}
    existing = session.exec(select(Cli)).all()
    existing_slugs = {c.slug for c in existing}

    to_remove = existing_slugs - incoming_slugs
    if existing_slugs and (len(to_remove) / len(existing_slugs)) >= mass_removal_threshold:
        raise MassRemovalBreaker(
            f"{len(to_remove)}/{len(existing_slugs)} removal >= {mass_removal_threshold}")

    added = 0
    for rec in incoming:
        adapter = _adapter_for(rec, adapters)
        declared = rec.declared_capability
        inferred = adapter.infer_capability(rec) if adapter else None
        merged = merge_capabilities(declared, inferred) or CapabilityRecord()
        merged = admit_ports(merged, vocab)
        launch = adapter.launch_spec(rec) if adapter else {}

        cli = session.get(Cli, rec.slug)
        if cli is None:
            cli = Cli(slug=rec.slug); added += 1
        cli.lang = rec.lang
        cli.path = rec.path
        cli.bucket = rec.bucket
        cli.project = rec.project
        cli.description = rec.description
        cli.source_class = rec.source_class
        cli.source_run_id = rec.source_run_id
        cli.last_seen_at = clock.now()
        cli.updated_at = clock.now()
        cli.launch_spec = _json.dumps(launch)
        session.add(cli)

        for old in session.exec(select(Capability).where(Capability.cli_slug == rec.slug)).all():
            session.delete(old)
        session.add(Capability(
            cli_slug=rec.slug,
            intent_tags=",".join(merged.intent_tags),
            input_types=",".join(merged.input_types),
            output_types=",".join(merged.output_types),
            side_effect=merged.side_effect,
            confidence=merged.confidence,
        ))

    for slug in to_remove:
        obj = session.get(Cli, slug)
        if obj:
            for old_cap in session.exec(
                select(Capability).where(Capability.cli_slug == slug)
            ).all():
                session.delete(old_cap)
            session.delete(obj)
    session.commit()

    edge_delta = compute_edges(session, vocab, clock)   # ONE batched recompute
    return {"added": added, "removed": len(to_remove), "edge_delta": edge_delta}
