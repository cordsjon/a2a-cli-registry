import json as _json
from sqlmodel import select
from core.models import Cli, Capability
from core.capability.model import CapabilityRecord, merge_capabilities, admit_ports
from core.graph.edges import compute_edges


class MassRemovalBreaker(RuntimeError):
    """>=threshold of existing CLIs would be removed — refuse, fail closed."""


# Capability-row and description owners the feed must not overwrite: an
# operator ("manual") or the capability-map backfill ("static"/"llm").
PRESERVED_PROVENANCE = ("manual", "static", "llm")

# US-CLIREG-POPULATE-DELETE-GUARD-01: the feed may only remove rows it owns.
# `to_remove = existing - incoming` used to cover every row; measured
# 2026-10-30 the committed feed (479 slugs, 2026-08-03) would have deleted 165
# of 641 live rows — 134 manual-register (bf-batch and every post-commit
# register_cli.py row), 24 external:nosignups, 1 manual_spec3 — at 25.7 %,
# under the 30 % breaker. A row whose source_class is outside this set was
# never the feed's to delete, whatever the feed says. (core/models.py calls
# source_class opaque; this guard is its one engine branch.)
FEED_OWNED_SOURCE_CLASSES = ("cli_audit",)


def _adapter_for(rec, adapters):
    for a in adapters:
        if a.detect(rec):
            return a
    return None


def _by_source_class(existing_by_slug, slugs) -> dict:
    groups: dict[str, list[str]] = {}
    for s in sorted(slugs):
        groups.setdefault(existing_by_slug[s].source_class or "", []).append(s)
    return groups


def populate(session, source, adapters, vocab, clock, mass_removal_threshold=0.30,
             feed_owned_source_classes=FEED_OWNED_SOURCE_CLASSES, dry_run=False):
    incoming = source.discover()                   # may raise SchemaError (fail closed)
    incoming_slugs = {r.slug for r in incoming}
    existing = session.exec(select(Cli)).all()
    existing_by_slug = {c.slug: c for c in existing}
    existing_slugs = set(existing_by_slug)

    absent = existing_slugs - incoming_slugs
    to_remove = {s for s in absent
                 if existing_by_slug[s].source_class in feed_owned_source_classes}
    protected = absent - to_remove
    breaker = bool(existing_slugs) and \
        (len(to_remove) / len(existing_slugs)) >= mass_removal_threshold
    if dry_run:
        # AC-01: the plan, grouped by source_class, before any write — nothing
        # above this line touched the session.
        return {"dry_run": True,
                "would_add": len(incoming_slugs - existing_slugs),
                "would_remove": _by_source_class(existing_by_slug, to_remove),
                "protected": _by_source_class(existing_by_slug, protected),
                "breaker_would_trip": breaker,
                "mass_removal_threshold": mass_removal_threshold}
    if breaker:
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

        # A row an operator hand-set (provenance='manual') is NOT the feed's to
        # overwrite. Without this, the delete+recreate below silently erases
        # every hand-fix on the next feed run: send_mail's intent_tags retag and
        # its output_types backfill were both lost this way, leaving two planner
        # tests red for ~2 months while the code that depended on them stayed
        # correct. Same protected marker tools/backfill_capabilities.py honours.
        # The capability-map backfill ('static'/'llm') is the second owner:
        # PRESERVED_PROVENANCE covers both, for the row and for the description.
        old_caps = session.exec(
            select(Capability).where(Capability.cli_slug == rec.slug)
        ).all()
        # The description guard is keyed on description_provenance alone, never
        # on the capability row's provenance (the two are owned independently).
        description_owned = any(
            c.description_provenance in PRESERVED_PROVENANCE for c in old_caps)

        cli = session.get(Cli, rec.slug)
        if cli is None:
            cli = Cli(slug=rec.slug); added += 1
        cli.lang = rec.lang
        cli.path = rec.path
        cli.bucket = rec.bucket
        cli.project = rec.project
        if not description_owned:
            cli.description = rec.description
        cli.source_class = rec.source_class
        cli.source_run_id = rec.source_run_id
        cli.not_standalone = rec.not_standalone
        cli.last_seen_at = clock.now()
        cli.updated_at = clock.now()
        cli.launch_spec = _json.dumps(launch)
        session.add(cli)

        # Scoped to this block rather than `continue`, so that anything added
        # later in the loop body still runs for a preserved row.
        if not any(c.provenance in PRESERVED_PROVENANCE for c in old_caps):
            # A feed-owned row whose only backfilled field is the description
            # (e.g. a shell CLI) is recreated, so its marker must be carried
            # over or the next run overwrites the description.
            description_marker = next(
                (c.description_provenance for c in old_caps
                 if c.description_provenance in PRESERVED_PROVENANCE), None)
            for old in old_caps:
                session.delete(old)
            session.add(Capability(
                cli_slug=rec.slug,
                intent_tags=",".join(merged.intent_tags),
                input_types=",".join(merged.input_types),
                output_types=",".join(merged.output_types),
                side_effect=merged.side_effect,
                confidence=merged.confidence,
                description_provenance=description_marker,
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
    return {"added": added, "removed": len(to_remove),
            "protected": _by_source_class(existing_by_slug, protected),
            "edge_delta": edge_delta}
