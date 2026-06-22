# Web Overview (Swagger-style) — Design Spec

**Date:** 2026-06-22
**Status:** Approved for implementation (revised after architecture/UI/test panel + Codex review)

---

## 0. Review history

This spec was revised after an adversarial pre-implementation review (architecture,
UI/UX, and test-design reviewers in parallel, plus an independent Codex pass).
Validated findings folded in:

- **launch_spec dropped from the page** (auth decision) — dissolves the open-route
  exposure inconsistency, the `include_launch_spec=True` flag requirement, AND the
  "launch_spec is a stored JSON *string*, not a dict" parsing trap in one cut.
- **`project` must be surfaced by the query layer** — `search_clis`/`describe_cli`
  did NOT return `Cli.project`, so the headline tab-grouping would have collapsed
  every CLI into `(ungrouped)`. Fixed by a dedicated batch query.
- **N+1 (~950 queries) eliminated** — a single batch overview query replaces the
  per-CLI `describe_cli` loop.
- **Accordion replaces 23 literal tabs** — 23 tabs wrap into an unusable multi-row
  strip; a vertical accordion is the actual Swagger mental model and needs less JS.
- **Client-side filter pulled into v1** — un-browsable at 103 cards/bucket without it.
- **Health badge carries a text/glyph label, not color alone** — accessibility.
- **Render tests made non-vacuous** — 2 buckets, ≥3 health states, DOM-level binding.
- **TestClient context-manager form mandated** — avoids the documented MCP-session leak.
- **Template packaging made explicit + loadability-tested.**

---

## 1. Goal

Serve a browsable, Swagger-style HTML page at `GET /overview` on the registry's
existing FastAPI app: a fleet-health header, a vertical accordion of project
buckets, a client-side filter, and an expandable detail card per CLI (capabilities,
incident chain edges, health). It is the human, in-browser counterpart to the
static terminal `overview` command and the machine-facing A2A/MCP surfaces — all
read the same catalog through `core.catalog.queries`.

---

## 2. Scope

**In scope:**
- One new route `GET /overview` returning a self-contained HTML page.
- A new batch query `overview_rows(session)` in `core.catalog.queries`.
- A pure view-model builder, a Jinja2 renderer, and one template.
- Vertical accordion of project buckets, client-side filter, expandable CLI cards,
  fleet-health header.
- Open access (no bearer), localhost-first, like `/health` and the agent card —
  but **without launch specs** (see §6).

**Out of scope (explicit YAGNI cuts, deferred):**
- Per-bucket health mini-counts in section headers (the global header covers totals).
- A dedicated call-graph diagram/tab (cards show their own incident edges only).
- Any write/mutation action from the page (read-only view).
- Auth/login on the page (intentionally open; see §6).
- Invoking/launching CLIs from the page — the registry never executes CLIs.
- **launch_spec on the page** — how-to-invoke detail stays behind the bearer-gated
  `/clis/{slug}` for agents (consistent with the unauthenticated-MCP redaction).

---

## 3. Architecture

A single server-rendered route on the existing app (`core/server/app.py`). No JS
framework, no build step, no external static assets.

```
Browser ──GET /overview──▶ FastAPI route (OPEN, no bearer)
                              │   with TestClient(app) lifespan semantics
                              ├─ queries.overview_rows(session)   → ONE batch read:
                              │     all Cli (slug, lang, project, description, health),
                              │     all Capability rows, all CliEdge rows
                              │     (health lowercased by _norm_health; NO launch_spec)
                              ▼
                       core.web.overview_view.build_overview_model(rows)
                              │   group by project bucket, attach caps + incident edges,
                              │   compute fleet health summary + version
                              ▼
                       core.web.render.render_overview_html(model)  (Jinja2)
                              ▼
                       HTMLResponse  (self-contained: inline CSS + minimal vanilla JS)
```

**Batch, not N+1.** `overview_rows` issues a bounded, fixed number of queries
(one `select(Cli)`, one `select(Capability)`, one `select(CliEdge)`), groups in
memory, and returns a flat structure. This replaces the rejected
`search_clis` + per-CLI `describe_cli` loop (~950 queries at 474 CLIs on an open,
uncached GET).

**Keystone (reworded).** `overview_rows` reuses `_norm_health` (the same central
normalizer `search_clis`/`describe_cli` use), so health display cannot drift.
Capability rows are returned **as stored** — "declared-wins" precedence is a
populate-time invariant (applied by `merge_capabilities` before rows are written),
NOT a query-layer guarantee; the page simply displays the already-resolved rows.

New runtime dependency: **`jinja2`** (FastAPI-native), confined to `core/web/`.

---

## 4. Components & File Structure

Mirrors the established `core/tui/` producer/presenter split: pure data-shaping
separated from the dependency-bearing renderer.

| File | Responsibility |
|---|---|
| `core/catalog/queries.py` | **Add** `overview_rows(session) -> dict`: one batch read of all CLIs (incl. `project`), all capabilities (grouped by slug), all edges. Reuses `_norm_health`. No launch_spec. |
| `core/web/__init__.py` | Package marker (empty). |
| `core/web/overview_view.py` | **Pure** `build_overview_model(rows) -> dict`. No Jinja, no FastAPI, no DB session. Groups by bucket, attaches caps + incident edges, computes summary. Unit-testable on plain dicts. |
| `core/web/render.py` | `render_overview_html(model) -> str`. The ONLY module importing `jinja2`. Builds a Jinja `Environment` with `PackageLoader("core.web", "templates")`, `autoescape=True`. |
| `core/web/templates/overview.html` | Health header, filter input, vertical accordion of bucket sections (native `<details>`), each holding expandable CLI cards (native `<details>`). Inline `<style>` + a small inline `<script>` for the filter only. No external assets. |
| `core/server/app.py` | Add `GET /overview` (open): open a request session, call `overview_rows`, `build_overview_model`, `render_overview_html`, return `HTMLResponse`. ~10 lines. |

**Boundaries:**
- `build_overview_model` is pure → tested without HTTP, DB, or a template engine.
- `render.py` is the only `jinja2` importer (isolation guard, like `rich` in `core/tui/`).
- The route is the only place query + view + render + FastAPI meet.

**Accordion + native `<details>` (binding):** both the bucket sections and the CLI
cards use native HTML `<details>/<summary>`. Expand/collapse therefore needs
**zero JavaScript** and is keyboard-accessible by default. The only inline JS is
the filter (§5). This is strictly less JS than the rejected tab design.

---

## 5. Data Flow & View-Model

### 5a. `overview_rows(session)` — the new batch query

Returns a flat, DB-free-consumable structure:

```python
{
  "clis": [   # one per Cli row
    {"slug": "download-bedca", "lang": "python", "project": "keto",
     "description": "download_bedca.py (keto)", "health_status": "unhealthy"}
  ],
  "caps_by_slug": {            # Capability rows grouped by cli_slug
    "download-bedca": [
      {"intent_tags": ["download"], "input_types": [], "output_types": [],
       "side_effect": "network", "confidence": "inferred"}
    ]
  },
  "edges": [   # all CliEdge rows
    {"from": "download-bedca", "to": "run-foodb-import", "via_type": "..."}
  ],
}
```

- `health_status` runs through `_norm_health` (lowercase canonical).
- `project` is included (the field neither `search_clis` nor `describe_cli` exposed).
- **No `launch_spec`** anywhere.
- Capability splitting reuses the same `.split(",")` shaping `_caps` already does
  (factor `_caps`'s row-shaping into a helper both can call, to avoid a second
  place to drift).

### 5b. `build_overview_model(rows)` — pure view-model

Returns exactly what the template iterates; the template holds no logic beyond
loops/conditionals:

```python
{
  "summary": {
    "total": 474,
    "healthy": 255, "unhealthy": 219, "stale": 0, "unknown": 0,
    "version": "1.2.0",                 # see version sourcing below
  },
  "buckets": [                          # accordion sections, sorted by name
    {
      "name": "keto",
      "count": 32,
      "clis": [                         # expandable cards, sorted by slug
        {
          "slug": "download-bedca",
          "lang": "python",
          "health_status": "unhealthy",
          "description": "download_bedca.py (keto)",
          "capabilities": [ {...} ],    # from caps_by_slug[slug], or [] if none
          "edges": [ {...} ],           # incident edges (slug is `from` OR `to`)
        }
      ]
    }
  ],
}
```

**Field sourcing / rules:**
- CLI rows + caps + edges all come from the single `overview_rows` result.
- `capabilities`: `caps_by_slug.get(slug, [])`.
- `edges`: filtered to edges where `slug == from` **or** `slug == to` (both directions).
- `summary` counts: one pass over `health_status`; assert `total == sum(parts)`.
- `version`: `importlib.metadata.version("a2a-cli-registry")`; on
  `PackageNotFoundError` (running from uninstalled source) fall back to reading
  `version` from `pyproject.toml`; if that also fails, `"unknown"`.

**Grouping:** by `project`. Missing/empty project → bucket `"(ungrouped)"`.
Real buckets sorted alphabetically; `"(ungrouped)"` pinned **last**. CLIs within a
bucket sorted by slug.

### 5c. Template behavior (accordion + filter + degenerate states)

- **Filter:** one `<input>` at top; ~8 lines of vanilla JS toggle `display:none`
  on any card whose `data-slug` + `data-desc` don't contain the (lowercased) query.
  All data is already in the DOM — pure local string match, zero network. A live
  "N of M shown" count sits next to the input.
- **Empty detail sections render nothing:** a card with no capabilities omits the
  Capabilities block entirely (no hollow heading); same for an edge-less card.
  (`{% if cli.capabilities %}` / `{% if cli.edges %}`.)
- **Health badge:** carries a glyph + the canonical text, not color alone —
  `● healthy`, `▲ unhealthy`, `◆ stale`, `○ unknown` — so it is legible to
  colorblind users and in monochrome. Color is an *additional* signal, not the only one.
- **Sticky bucket headers** (`position: sticky`) so the active bucket stays labeled
  while scrolling a long section.

---

## 6. Auth & Security

- The `/overview` route and its data are **open** (no bearer), matching `/health`
  and `/.well-known/agent-card.json`. The registry is local-first (binds 127.0.0.1).
- **launch_spec is NOT rendered.** The page shows capabilities, health, edges,
  paths-as-description, and lang only. This keeps the open page consistent with the
  existing redaction boundary — there is an explicit test that an unauthenticated
  MCP client does NOT receive `launch_spec` (`tests/test_mcp.py`); the open HTML
  page upholds the same contract. How-to-invoke detail stays behind bearer-gated
  `/clis/{slug}`.
- **Jinja2 autoescape ON.** Slugs/descriptions originate from an operator-populated
  cli-audit export; all fields render through `{{ }}` (never `| safe`). Any data
  placed into the inline filter JS (if any) must use `| tojson`; the design avoids
  embedding row data in JS entirely — the filter reads `data-*` attributes, which
  are autoescaped.
- No change to the bearer-gated routes (`/clis`, `/clis/{slug}`, `/graph`, `/a2a`)
  or the MCP sub-app.

---

## 7. Error Handling

- **Empty registry:** header renders with all-zero totals plus an "empty —
  run `populate`" notice; no accordion sections.
- **CLI with no capabilities / no edges:** card renders, the empty detail
  section(s) omitted (no crash, no hollow headings). This is the *common* case
  (many real CLIs have no inferred capability), not an edge case.
- **Render/template failure:** the route lets the exception propagate to FastAPI's
  default handler (500). No bare `except`; no partial HTML.
- **No auth-failure path** (route is open by design).

---

## 8. Testing

Tests must be non-vacuous: assert *binding* (this field → this element) on fixtures
with enough variety that a broken template can't accidentally satisfy them.

- **`core/catalog/queries.py::overview_rows`** (DB, via conftest fixtures):
  - returns `project` for each CLI (the field the old queries dropped);
  - `health_status` is lowercased (seed an uppercase row, assert canonical);
  - capabilities grouped by slug; edges complete;
  - **no `launch_spec`** key anywhere in the result;
  - issues a bounded number of queries (assert it does NOT scale per-CLI — e.g.
    seed 10 CLIs and assert the same call shape as 2 CLIs; a query-count spy or a
    structural assertion that no per-slug loop exists).
- **`core/web/overview_view.py`** (pure, no HTTP/Jinja/DB):
  - groups by `project` into correct buckets, sorted, `(ungrouped)` pinned last;
  - `(ungrouped)` fallback for BOTH missing-key and empty-string project;
  - health-summary counts over a set containing **all five** states, and
    `total == healthy + unhealthy + stale + unknown`;
  - incident-edge filtering matches a CLI as `from` AND (separate fixture) as `to`;
  - a CLI with empty caps → card dict with `capabilities == []`, no crash;
  - empty-input → zeroed summary, no buckets;
  - version fallback: monkeypatch `importlib.metadata.version` to raise →
    assert the `"unknown"` (or pyproject) branch is taken.
- **`core/web/render.py`** (Jinja):
  - fixture with **two buckets** and CLIs of **distinct health states**; assert
    each card binds ITS OWN health (the `unhealthy` card contains "unhealthy" and
    not "healthy"; the `healthy` card the reverse) — slice per-card, don't substring
    the whole doc;
  - assert BOTH bucket names appear (catches a dropped-bucket regression);
  - assert the health badge contains the text label, not just a color class;
  - **template loadability:** `render_overview_html({...empty...})` returns
    `<html`-containing output (proves `PackageLoader` finds the template — guards
    against a missing-from-package template);
  - **XSS:** a description `"<script>__XSS__()</script>"` → assert
    `"&lt;script&gt;__XSS__"` present AND `"<script>__XSS__"` absent (sentinel
    avoids false-positive on the legitimate inline filter `<script>`).
- **`core/server/app.py`** (FastAPI `TestClient`, **context-manager form**
  `with TestClient(app) as client:` — required to run the MCP lifespan and avoid the
  documented session leak):
  - `GET /overview` → 200, `content-type: text/html`, body contains a seeded slug,
    its bucket name, and the fleet-summary totals;
  - empty-DB → 200 with the empty notice;
  - **open-route proof:** set `A2A_BEARER_TOKEN`, assert `/overview` still 200s
    WITHOUT a token header while `/clis` 401s in the same test (proves genuinely
    exempt, not just untested-because-no-token);
  - **500 path:** monkeypatch the renderer to raise, `TestClient(app,
    raise_server_exceptions=False)`, assert 500.
- **Dependency isolation:** extend the packaging guard so `jinja2` is imported only
  under `core/web/` (as `rich` is confined to `core/tui/`).
- **Packaging:** `jinja2` declared in `pyproject.toml` `dependencies` (assert);
  the template ships — declare `core/web/templates/*.html` as package data via
  hatchling and assert that declaration exists (the loadability test above is the
  runtime complement).

---

## 9. Success Criteria

- `GET /overview` on a populated registry returns a browsable HTML page with:
  a fleet-health header (total + healthy/unhealthy/stale/unknown badges + version),
  a vertical accordion of project buckets, a working client-side filter, and an
  expandable card per CLI (capabilities, incident edges, health badge with text label).
- Filter and expand/collapse work with no network round-trip (expand/collapse via
  native `<details>`, zero JS; filter via inline JS over `data-*`).
- Health badges show the real lowercase canonical states with text labels.
- The page never renders `launch_spec`.
- All catalog data flows through `core.catalog.queries.overview_rows` (the one new
  query); the read is batched (no per-CLI N+1).
- `jinja2` is imported only under `core/web/`; the template ships in the package.
- The page is reachable without a bearer token; bearer-gated routes unchanged.
- Full test suite green. Version bumped (1.1.0 → 1.2.0); the existing
  `test_version_is_1_1_0` updated accordingly.

---

## 10. File Structure Summary

| File | Create / Modify |
|---|---|
| `core/catalog/queries.py` | Modify (add `overview_rows`; factor shared cap-row shaping) |
| `core/web/__init__.py` | Create |
| `core/web/overview_view.py` | Create |
| `core/web/render.py` | Create |
| `core/web/templates/overview.html` | Create |
| `core/server/app.py` | Modify (add `/overview` route) |
| `pyproject.toml` | Modify (add `jinja2` dep; template package-data; version → 1.2.0) |
| `tests/test_catalog.py` | Modify (add `overview_rows` tests) |
| `tests/test_web_overview_view.py` | Create |
| `tests/test_web_render.py` | Create |
| `tests/test_server_overview.py` | Create |
| `tests/test_packaging.py` | Modify (jinja2 declared + import isolation + version + template-ships) |
| `README.md` / `CHANGELOG.md` | Modify (document the page) |
