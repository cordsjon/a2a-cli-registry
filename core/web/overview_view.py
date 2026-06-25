import importlib.metadata
from pathlib import Path
import tomllib


_CANON_HEALTH = {"healthy", "unhealthy", "stale", "unknown"}
_UNGROUPED = "(ungrouped)"
_HEALTH_GLYPHS = {
    "healthy": "\u25cf",
    "unhealthy": "\u25b2",
    "stale": "\u25c6",
    "unknown": "\u25cb",
}


def _norm_health(value):
    state = (value or "unknown").lower()
    return state if state in _CANON_HEALTH else "unknown"


def _bucket_name(cli):
    project = cli.get("project")
    if project is None or project == "":
        return _UNGROUPED
    return project


def _pyproject_version():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        cfg = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return cfg.get("project", {}).get("version")


def _package_version():
    try:
        return importlib.metadata.version("a2a-cli-registry")
    except importlib.metadata.PackageNotFoundError:
        return _pyproject_version() or "unknown"


def build_overview_model(rows) -> dict:
    clis = rows.get("clis", [])
    caps_by_slug = rows.get("caps_by_slug", {})
    edges = rows.get("edges", [])
    summary = {
        "total": len(clis),
        "healthy": 0,
        "unhealthy": 0,
        "stale": 0,
        "unknown": 0,
        "version": _package_version(),
    }
    buckets = {}

    for cli in clis:
        state = _norm_health(cli.get("health_status"))
        summary[state] += 1
        slug = cli["slug"]
        desc = cli.get("description") or ""
        # A description on an unhealthy CLI is the probe/audit failure note (e.g.
        # "ModuleNotFoundError: numpy"), not a summary of what the tool does. Flag
        # it so the UI can render it as a subtle status line rather than a
        # description. Healthy CLIs carry their real --help one-liner.
        desc_is_error = bool(desc) and state == "unhealthy"
        card = {
            "slug": slug,
            "lang": cli.get("lang") or "",
            "health_status": state,
            "health_glyph": _HEALTH_GLYPHS[state],
            "description": desc,
            "desc_is_error": desc_is_error,
            "capabilities": caps_by_slug.get(slug, []),
            "edges": [
                edge for edge in edges
                if edge.get("from") == slug or edge.get("to") == slug
            ],
        }
        buckets.setdefault(_bucket_name(cli), []).append(card)

    ordered_names = sorted(name for name in buckets if name != _UNGROUPED)
    if _UNGROUPED in buckets:
        ordered_names.append(_UNGROUPED)

    assert summary["total"] == (
        summary["healthy"] + summary["unhealthy"] + summary["stale"] + summary["unknown"]
    )

    return {
        "summary": summary,
        "buckets": [
            {
                "name": name,
                "count": len(buckets[name]),
                "clis": sorted(buckets[name], key=lambda row: row["slug"]),
            }
            for name in ordered_names
        ],
    }
