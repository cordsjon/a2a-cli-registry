"""okf-produce: render the catalog as a deterministic OKF bundle."""
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.catalog.queries import export_rows
from core.okf.frontmatter import join_doc, split_doc, content_hash

OKF_VERSION = "0.1"


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _iso(updated_at):
    if updated_at is None:
        return None
    return datetime.fromtimestamp(float(updated_at), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _bucket(project):
    return project if project else "_unbucketed"


def _concept_id(row):
    return f"clis/{_bucket(row['project'])}/{row['slug']}"


def _resource(path):
    return f"file://{path}" if path else None


def _is_bundle_dir(out: Path) -> bool:
    idx = out / "index.md"
    return idx.exists() and "okf_version" in idx.read_text(encoding="utf-8")


def _existing_enrichment(path: Path):
    """Return (description, enriched_against) preserved from a prior concept file."""
    if not path.exists():
        return None, None
    try:
        fm, _ = split_doc(path.read_text(encoding="utf-8"))
    except ValueError:
        return None, None
    return fm.get("description"), fm.get("enriched_against")


def produce_bundle(session, out_dir, force=False) -> dict:
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()) and not _is_bundle_dir(out) and not force:
        raise FileExistsError(
            f"{out_dir} is non-empty and not an OKF bundle; pass force=True to overwrite")

    rows = export_rows(session)
    max_updated = max((r["updated_at"] or 0.0) for r in rows) if rows else 0.0

    # concept files
    for row in rows:
        cid = _concept_id(row)
        cap = row["capability"] or {"intent_tags": [], "input_types": [],
                                    "output_types": [], "side_effect": "unknown",
                                    "confidence": "declared"}
        resource = _resource(row["path"])
        chash = content_hash(
            concept_id=cid, slug=row["slug"], lang=row["lang"],
            project=row["project"], resource=resource,
            intent_tags=cap["intent_tags"], input_types=cap["input_types"],
            output_types=cap["output_types"], side_effect=cap["side_effect"],
            confidence=cap["confidence"], edges=row["edges"])

        path = out / (cid + ".md")
        prior_desc, prior_enriched = _existing_enrichment(path)
        description = prior_desc if prior_desc is not None else row["description"]

        fm = {"type": "cli", "title": row["slug"], "description": description}
        if resource:
            fm["resource"] = resource
        fm["tags"] = cap["intent_tags"]
        ts = _iso(row["updated_at"])
        if ts:
            fm["timestamp"] = ts
        fm["content_hash"] = chash
        if prior_enriched:
            fm["enriched_against"] = prior_enriched
        fm["ports"] = {"in": cap["input_types"], "out": cap["output_types"]}
        fm["side_effect"] = cap["side_effect"]
        fm["confidence"] = cap["confidence"]
        fm["health"] = row["health_status"]
        fm["edges"] = row["edges"]

        body = _render_body(row, cap, rows)
        _atomic_write(path, join_doc(fm, body))

    # reserved files (deterministic; no wall-clock)
    _atomic_write(out / "index.md", _render_index(rows))
    _atomic_write(out / "log.md", _render_log(max_updated))
    return {"concepts": len(rows)}


def _rel_link(from_row, to_slug, rows):
    to_row = next((r for r in rows if r["slug"] == to_slug), None)
    if to_row is None:
        return f"{to_slug}.md"
    from_dir = f"clis/{_bucket(from_row['project'])}"
    to_path = f"clis/{_bucket(to_row['project'])}/{to_slug}.md"
    return os.path.relpath(to_path, from_dir)


def _render_body(row, cap, rows) -> str:
    lines = ["## Capabilities", ""]
    ins = ", ".join(f"`{t}`" for t in cap["input_types"]) or "(none)"
    outs = ", ".join(f"`{t}`" for t in cap["output_types"]) or "(none)"
    lines.append(f"Reads {ins}, produces {outs}. "
                 f"Side effect: {cap['side_effect']}. ({cap['confidence']})")
    if row["edges"]:
        lines += ["", "## Chains into", ""]
        for e in row["edges"]:
            link = _rel_link(row, e["to"], rows)
            lines.append(f'- [{e["to"]}]({link} "via {e["via"]}")')
    return "\n".join(lines) + "\n"


def _render_index(rows) -> str:
    lines = [f"okf_version: {OKF_VERSION}", "", "# Bundle Index", ""]
    for r in rows:
        lines.append(f"- {_concept_id(r)}")
    return "\n".join(lines) + "\n"


def _render_log(max_updated) -> str:
    stamp = _iso(max_updated) if max_updated else "(empty)"
    return f"# Log\n\nLast structural change: {stamp}\n"
