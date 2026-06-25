"""okf-ingest: read enriched descriptions back into the catalog.

Writes ONLY Cli.description. All structural frontmatter is read-and-discarded;
structure stays connector-owned (spec §5).
"""
import sys
from pathlib import Path

from core.models import Cli
from core.okf.frontmatter import split_doc

_RESERVED = {"index.md", "log.md"}


def _slug_from_path(path: Path, bundle: Path) -> str:
    # concept id = clis/<bucket>/<slug>; slug is the filename stem
    return path.stem


def ingest_bundle(session, bundle_dir) -> dict:
    bundle = Path(bundle_dir)
    updated = skipped = failed = 0
    for path in sorted(bundle.rglob("*.md")):
        if path.name in _RESERVED:
            continue
        try:
            fm, body = split_doc(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"okf-ingest: malformed concept {path}: {exc}", file=sys.stderr)
            failed += 1
            continue
        slug = _slug_from_path(path, bundle)
        cli = session.get(Cli, slug)
        if cli is None:
            print(f"okf-ingest: unknown slug {slug!r} ({path}); skipped",
                  file=sys.stderr)
            skipped += 1
            continue
        new_desc = fm.get("description", "")
        if new_desc != (cli.description or ""):
            cli.description = new_desc          # the ONLY field written
            session.add(cli)
            updated += 1
    session.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed}
