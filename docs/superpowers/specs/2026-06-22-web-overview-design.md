# Web Overview (Swagger-style) — Design Spec

**Date:** 2026-06-22
**Status:** Approved for implementation

---

## 1. Goal

Serve a browsable, Swagger-style HTML page at `GET /overview` on the registry's
existing FastAPI app: a fleet-health header, one tab per project bucket, and a
full-detail expandable card per CLI (capabilities, launch spec, incident chain
edges, health). It is the human, in-browser counterpart to the static terminal
`overview` command and the machine-facing A2A/MCP surfaces — all three read the
same catalog through the same `core.catalog.queries` functions.

---

## 2. Scope

**In scope:**
- One new route `GET /overview` returning a self-contained HTML page.
- A pure view-model builder, a Jinja2 renderer, and one template.
- Grouping by project bucket (tabs), full-detail CLI cards, fleet-health header.
- Open access (no bearer), localhost-first, like `/health` and the agent card.

**Out of scope (explicit YAGNI cuts, deferred):**
- Live in-browser filter box (the CLI `overview --query` covers filtering).
- Per-tab health mini-counts in tab labels.
- A dedicated call-graph diagram/tab (cards show their own incident edges only).
- Any write/mutation action from the page (read-only view).
- Auth/login on the page (it is intentionally open; see §6).
- Invoking/launching CLIs from the page (the registry never executes CLIs;
  it serves metadata only — this view keeps that boundary).

---

## 3. Architecture

A single server-rendered route on the existing app (`core/server/app.py`). No
JS framework, no build step, no external static assets.

```
Browser ──GET /overview──▶ FastAPI route (OPEN, no bearer)
                              │
                              ├─ queries.search_clis(session, "")     → all CLI rows
                              ├─ queries.describe_cli(session, slug)   → caps + launch_spec per CLI
                              ├─ queries.cli_graph(session)            → all chain edges
                              │     (health already lowercased by queries._norm_health)
                              ▼
                       core.web.overview_view.build_overview_model(clis, graph)
                              │   group by project bucket, attach caps/launch_spec/incident edges,
                              │   compute fleet health summary + version
                              ▼
                       core.web.render.render_overview_html(model)  (Jinja2)
                              ▼
                       HTMLResponse  (self-contained: inline CSS + minimal vanilla JS)
```

**Keystone:** the page reads the SAME `queries` functions as the CLI `overview`
and the A2A/MCP ops, so it inherits the `_norm_health` lowercase normalization
and declared-wins capability precedence with no second place to drift.

New runtime dependency: **`jinja2`** (FastAPI-native), confined to `core/web/`.

---

## 4. Components & File Structure

Mirrors the established `core/tui/` producer/presenter split: pure data-shaping
separated from the dependency-bearing renderer.

| File | Responsibility |
|---|---|
| `core/web/__init__.py` | Package marker (empty). |
| `core/web/overview_view.py` | **Pure** `build_overview_model(clis, graph) -> dict`. No Jinja, no FastAPI. Groups by bucket, enriches each CLI (capabilities, launch_spec, incident edges), computes the summary. Unit-testable on plain dicts. |
| `core/web/render.py` | `render_overview_html(model) -> str`. The ONLY module importing `jinja2`. Builds a Jinja `Environment` with a `PackageLoader`/`FileSystemLoader` rooted at the templates dir, autoescape ON. |
| `core/web/templates/overview.html` | The template: health header, tab strip (one per bucket), tab panels of expandable full-detail CLI cards. Inline `<style>` + a small inline `<script>` for tab switch + card expand. No external assets. |
| `core/server/app.py` | Add `GET /overview` (open): open a request session, call the three queries, enrich via `describe_cli`, `build_overview_model`, `render_overview_html`, return `HTMLResponse`. ~10–15 lines. |

**Boundaries:**
- `build_overview_model` is pure → tested without HTTP or a template engine.
- `render.py` is the only `jinja2` importer (isolation guard, like `rich` in `core/tui/`).
- The route is the only place queries + view + render + FastAPI meet.

**Enrichment (binding):** `search_clis` returns slug/lang/description/
health_status (no capabilities). The **route** enriches each row with
`describe_cli(session, slug)` (attaching `capabilities` + `launch_spec`, with
the `None` guard) BEFORE calling `build_overview_model`. The builder receives a
list of already-enriched CLI dicts plus the graph and stays **DB-free** — no
session, no `describe` callable threaded in. This keeps the builder a pure
data-shaping function (grouping, summary, edge-filtering) testable on plain
dicts, exactly as `core/tui` render is.

---

## 5. Data Flow & View-Model

`build_overview_model(clis, graph)` returns exactly what the template iterates;
the template holds no logic beyond loops/conditionals.

```python
{
  "summary": {
    "total": 474,
    "healthy": 255, "unhealthy": 219, "stale": 0, "unknown": 0,
    "version": "1.1.0",                 # importlib.metadata.version("a2a-cli-registry")
  },
  "buckets": [                          # one tab per bucket, sorted by name
    {
      "name": "keto",
      "count": 32,
      "clis": [                         # full-detail cards, sorted by slug
        {
          "slug": "download-bedca",
          "lang": "python",
          "health_status": "unhealthy", # lowercase canonical (from queries)
          "description": "download_bedca.py (keto)",
          "capabilities": [
            {"intent_tags": ["download"], "input_types": [], "output_types": [],
             "side_effect": "network", "confidence": "inferred"}
          ],
          "launch_spec": { "kind": "python_module", "entrypoint": "...", "args_schema": {} },
          "edges": [                     # incident edges (CLI is `from` OR `to`)
            { "from": "download-bedca", "to": "run-foodb-import", "via_type": "..." }
          ]
        }
      ]
    }
  ]
}
```

**Field sourcing:**
- CLI rows: `search_clis` (slug/lang/description/health_status).
- `capabilities`, `launch_spec`: `describe_cli(slug)` per CLI; guard `None` →
  empty capabilities `[]` and empty launch_spec `{}` (the CLI overview's
  `desc if desc else …` guard pattern).
- `edges`: `cli_graph()` filtered to edges where the slug is `from` or `to`.
- `summary` counts: one pass over CLI health_status values.
- `version`: `importlib.metadata.version("a2a-cli-registry")`; if the package
  metadata is unavailable (running from source uninstalled), fall back to
  reading the `version` from `pyproject.toml`, else `"unknown"`.

**Grouping:** by the `project` field. Missing/empty project → bucket
`"(ungrouped)"`. Buckets sorted alphabetically; CLIs within a bucket by slug.

---

## 6. Auth & Security

- The `/overview` route and the data it renders are **open** (no bearer
  dependency), matching the existing `/health` and `/.well-known/agent-card.json`
  routes. The catalog is non-secret metadata and the registry is local-first
  (binds 127.0.0.1 by default).
- The page renders catalog metadata only. It never executes a CLI and exposes no
  mutation — consistent with the registry's "serve data, never run" boundary.
- Jinja2 autoescape is ON: CLI slugs/descriptions/paths originate from an
  operator-populated cli-audit export, but are still escaped so a crafted
  description cannot inject markup into the page.
- No change to the bearer-gated routes (`/clis`, `/clis/{slug}`, `/graph`,
  `/a2a`) or the MCP sub-app.

---

## 7. Error Handling

- **Empty registry:** header renders with all-zero totals plus an "empty —
  run `populate`" notice; no tabs. (Mirrors the CLI overview empty message.)
- **`describe_cli` returns `None`** for a slug from `search_clis` (deleted
  between the two queries): that card shows empty capabilities/launch_spec,
  never a `KeyError`.
- **Render/template failure:** the route lets the exception propagate to
  FastAPI's default handler (500). No bare `except` swallowing; no partial HTML.
- **No auth-failure path** (route is open by design).

---

## 8. Testing

- **`core/web/overview_view.py`** (pure, no HTTP/Jinja):
  - groups CLIs by `project` into the right buckets, sorted;
  - `(ungrouped)` fallback for missing project;
  - health-summary counts correct over a mixed set;
  - incident-edge filtering (a CLI sees only edges it participates in);
  - `None`-describe guard yields empty caps/launch_spec, no crash;
  - empty-input → zeroed summary, no buckets.
- **`core/web/render.py`:** `render_overview_html(model)` returns HTML
  containing a known slug, a health-badge marker, and a bucket tab label —
  proves the template binds to the model (analogous to the `export_text()`
  TUI tests). Asserts autoescaping (a `<script>` in a description renders
  escaped, not live).
- **`core/server/app.py`** (FastAPI `TestClient`):
  - `GET /overview` → 200, `content-type: text/html`, body contains a seeded
    CLI slug + the fleet-summary totals;
  - empty-DB → 200 with the empty notice;
  - the route requires NO bearer (a tokenless request still 200s).
- **Dependency isolation:** extend the existing packaging guard so `jinja2`
  is imported only under `core/web/` (as `rich` is confined to `core/tui/`).
- **Packaging:** `jinja2` declared in `pyproject.toml` `dependencies`; a
  packaging test asserts it.

---

## 9. Success Criteria

- `GET /overview` on a populated registry returns a browsable HTML page with:
  a fleet-health header (total + healthy/unhealthy/stale/unknown badges +
  version), one tab per project bucket, and a full-detail expandable card per
  CLI (capabilities, launch spec, incident edges, health badge).
- Tab switching and card expand/collapse work with no network round-trip.
- Health badges show the real lowercase canonical states.
- All catalog data flows through existing `queries` functions (no new SQL).
- `jinja2` is imported only under `core/web/`.
- The page is reachable without a bearer token; bearer-gated routes unchanged.
- Full test suite green. Version bumped (1.1.0 → 1.2.0) since a new public
  surface is added.

---

## 10. File Structure Summary

| File | Create / Modify |
|---|---|
| `core/web/__init__.py` | Create |
| `core/web/overview_view.py` | Create |
| `core/web/render.py` | Create |
| `core/web/templates/overview.html` | Create |
| `core/server/app.py` | Modify (add `/overview` route) |
| `pyproject.toml` | Modify (add `jinja2` dep; version → 1.2.0) |
| `tests/test_web_overview_view.py` | Create |
| `tests/test_web_render.py` | Create |
| `tests/test_server_overview.py` | Create |
| `tests/test_packaging.py` | Modify (jinja2 declared + import-isolation guard) |
| `README.md` / `CHANGELOG.md` | Modify (document the page) |
