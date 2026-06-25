# a2a-cli-registry — OKF Producer Design Spec

**Date:** 2026-06-25
**Status:** Pre-implementation design spec (brainstorming gate output).
**Author:** Jonas Cords + Claude (Opus 4.8)
**Scope:** Add an Open Knowledge Format (OKF) interchange surface to the existing
v1.2 registry — an `okf-produce` exporter and a descriptions-only `okf-ingest`
importer. SQLite remains the source of truth. A2A/MCP serve surfaces are untouched.

---

## 1. Motivation

Two OSS projects independently converged on the same primitive the registry
already embodies: **typed Markdown + YAML knowledge bundles, deterministically
extracted, LLM-enriched, served over MCP, local-first and Git-diffable.**

- **OKFy** (`0dust/OKFy`, TypeScript) — the OKF format + an MCP reader
  (`search_concepts`, `read_concept`, `get_neighbors`, `bundle_summary`).
- **okf-skills** (`xSAVIKx/okf-skills`, Go) — a *factory* of connectors that
  `produce` OKF bundles from data sources, with the lifecycle
  `produce → enrich → ingest --sync → viz render`.
- **Canonical spec:** `GoogleCloudPlatform/knowledge-catalog/okf` (OKF v0.1 draft).

`a2a-cli-registry` catalogs the **local CLI fleet as typed, chainable tools**.
That is structurally an OKF producer whose concepts are CLIs. Adopting the OKF
envelope makes the registry's output consumable by any OKF-aware agent (and
`okf-viz`, `okf-mcp`, OKFy) without abandoning its differentiators: the typed
I/O ports, the side-effect classification, and the computed call-graph.

**The win:** standard envelope, registry-specific payload survives as
spec-permitted producer extensions (OKF §4).

### Non-goals

- SQLite is **not** replaced as the source of truth (export-only adoption).
- No rewrite of `populate`, `discover`, `serve`, the A2A surface, or the MCP
  surface. This is additive.
- No structural write-back on ingest (descriptions only — see §5).
- Not a reimplementation of `okf-viz`/`okf-mcp` — we *produce* a bundle those
  existing tools already consume.

---

## 2. The OKF Contract (as adopted)

A **bundle** is a directory tree of UTF-8 Markdown files, each with a YAML
frontmatter block delimited by `---`. A **concept** is one such file; its
**concept ID** is the file path within the bundle minus the `.md` suffix
(OKF §2). Relationships between concepts are standard Markdown links in the
body; reserved filenames `index.md` and `log.md` are not concepts.

**Standard frontmatter fields** (from `okf-go` `Frontmatter`):
`type`, `title`, `description`, `resource`, `tags[]`, `timestamp`,
`content_hash`, `enriched_against`, `okf_version` (root `index.md` only).

OKF §4 explicitly permits producer-defined extra frontmatter keys; the registry
uses that allowance for `ports`, `side_effect`, `confidence`, and `health`.

---

## 3. Architecture & Module Boundary

New module `core/okf/` is the **only** place that knows the OKF serialization
format (mirrors how `core/tui/` is the only `rich`-importing module).

```
core/okf/
  __init__.py
  frontmatter.py  # OKF Frontmatter dataclass + YAML read/write + "---" boundary contract
  serialize.py    # SQLite rows -> OKF ConceptDoc -> ./bundle/*.md   (produce)
  parse.py        # ./bundle/*.md -> {slug: description}              (ingest, descriptions only)
```

**Dependency direction:** `core/okf/` depends on `core/store` (a session) and
on `core/catalog/queries.cli_graph` for edges. Never the reverse. `serve`/MCP/A2A
are not imported and not modified.

**Read boundary (corrected after review).** The existing projections
`overview_rows`/`describe_cli` deliberately drop `Cli.path` and `Cli.updated_at`
(`core/catalog/queries.py:39`, `:64`) — but the OKF mapping needs both
(`resource`, `timestamp`). Produce therefore adds **one export-specific query**,
`export_rows(session)` in `core/catalog/queries.py`, returning the full `Cli`
row + its `Capability` + its outbound `CliEdge` rows, with a **stable total
order** (see §6). `core/okf/` does not re-select model tables ad hoc; it consumes
`export_rows` so the ordering guarantee lives in one place.

**Two new CLI commands**, added to the existing single-positional `choices`
list in `core/cli/main.py` (the same pattern as `probe`/`overview`, not
subparsers):

| Command | Reads | Writes | Lock |
|---|---|---|---|
| `okf-produce --out ./bundle [--force]` | SQLite (read-only) | `./bundle/*.md` | none on DB (read-only) |
| `okf-ingest --bundle ./bundle` | bundle files | `Cli.description` only | `with_file_lock` + busy-timeout |

New flags `--out` (default `./bundle`) and `--bundle` (default `./bundle`) are
added via `add_argument`; the existing `parse_known_args` tolerance is preserved.

---

## 4. Bundle Layout & Frontmatter Mapping

```
bundle/
  index.md                      # reserved: root listing; carries okf_version: "0.1"
  log.md                        # reserved: produce timestamp + run provenance
  clis/
    <project>/                  # subdir per Cli.project (bucketing -> OKF subdirs)
      <slug>.md                 # one concept per CLI; concept ID = clis/<project>/<slug>
```

CLIs with no `project` go to `clis/_unbucketed/`.

**Capability multiplicity invariant (corrected after review).** `Capability` is
its own table with its own PK (`core/models.py:24`); the model permits >1 row per
CLI, and query/planner code treats capabilities as lists
(`core/catalog/queries.py:24`, `core/planner/search.py:26`). Current `populate`
writes **exactly one** capability row per CLI (delete-then-insert,
`core/populate.py:54`). OKF v1 exports that invariant directly: **one capability
per CLI**, and produce **fails loudly** if `export_rows` returns a CLI with >1
capability row (rather than silently picking one). A future `capabilities: [...]`
aggregation is a v2 concern, explicitly out of scope here.

**Per-CLI concept frontmatter** (standard fields + producer extensions):

```yaml
---
type: cli                          # standard
title: pdf2text                    # standard  <- Cli.slug
description: "Convert PDF to text" # standard  <- Cli.description (ONLY enrichable field)
resource: "file:///opt/bin/pdf2text"  # standard <- Cli.path as file:// URI; omitted if path is null
tags: [convert, document]          # standard  <- Capability.intent_tags (sorted)
timestamp: "2026-06-25T12:00:00Z"  # standard  <- Cli.updated_at as ISO 8601 UTC
content_hash: "sha256:<hex>"       # standard  <- structural hash (see §6)
enriched_against: "sha256:<hex>"   # standard  <- carried forward from prior bundle if present
# --- producer extensions (a2a-cli-registry) ---
ports:
  in:  [file:pdf]                  # <- Capability.input_types (sorted) — NODE I/O, not edges
  out: [text]                      # <- Capability.output_types (sorted)
side_effect: none                  # <- Capability.side_effect
confidence: declared               # <- Capability.confidence (declared/inferred)
health: healthy                    # <- Cli.health_status (informational; NEVER ingested)
edges:                             # <- the authoritative typed graph (sorted by to,via)
  - to: summarize                  #    <- CliEdge.to_slug
    via: text                      #    <- CliEdge.via_type
---
## Capabilities
Reads `file:pdf`, produces `text`. No side effects. (declared)

## Chains into
- [summarize](../_unbucketed/summarize.md "via text")
```

**Edge representation (corrected after review).** The earlier draft claimed
`ports` represented edges — that is wrong. `ports` are **node I/O only**; an
actual `CliEdge` exists only after `core/graph/edges.py` applies
vocabulary-eligibility + hub-type gating (`core/graph/edges.py:27`). A
ports-only recompute would *invent* edges the gating rejected. So edges are
represented **three ways with a clear authority order**:

1. **`edges:` frontmatter list** — the machine-recoverable typed graph
   (`to` + `via`), copied verbatim from the computed `CliEdge` rows. This is the
   recommended ingest source for OKF-aware consumers.
2. **`## Chains into` body Markdown links** — same edges as relative links with
   `via_type` in the link title, so generic OKF tools (`get_neighbors`) traverse
   the graph without parsing producer extensions.
3. **`ports`** — node I/O for display and for *recomputation* only; never treated
   as edges.

`edges:` and the body links are produced from the **same** `CliEdge` set and
MUST agree (a test asserts this). Edge links use relative paths between concept
files.

**Never emitted:** `launch_spec` (matches the existing `/overview`
trust-boundary rule — the bundle is open/shareable; launch specs are not).

**`resource`:** OKF wants a canonical URI. `Cli.path` is rendered as a
`file://` URI. CLIs without a `path` omit `resource` (it is optional).

---

## 5. Ingest Safety (descriptions only)

`okf-ingest` parses each concept and updates **only** `Cli.description` for the
matching slug, under `with_file_lock` + the existing SQLite busy-timeout.

- **Read but discarded** on ingest: `ports`, `side_effect`, `tags`,
  `confidence`, `health`, and all edges. Structure is connector-owned; this
  enforces the registry's "declared / connector always wins over the bundle"
  precedence at the import boundary.
- **Slug resolution:** concept ID `clis/<project>/<slug>` -> `<slug>`. An
  unknown slug (e.g. a CLI removed since the bundle was produced) is **skipped
  with a loud warning** and counted in the summary — not a hard failure.
- **`enriched_against` (corrected after review):** ingest does **not** stamp
  provenance — that would require either mutating the bundle or a new DB column,
  both of which contradict descriptions-only. `enriched_against` is a
  **produce-side, bundle-only** field: on produce, if a concept file already
  exists with `description` + `enriched_against`, those two are preserved
  verbatim (§6). The registry's `Cli` row gains no new column. Whoever authored
  the enriched description (the enrich agent / human, following OKF's enrich
  model) is responsible for setting `enriched_against` in the bundle file;
  ingest only reads `description` from it.

---

## 6. Determinism (`content_hash`)

Each concept's `content_hash` is `sha256:` over a **canonical structural
tuple** (revised after review to include emitted connector-owned fields that
affect produced bytes — a CLI move or path change MUST change the hash):

```
(concept_id, slug, lang, project, resource,
 sorted(intent_tags), sorted(input_types), sorted(output_types),
 side_effect, confidence, sorted(edges as (to_slug, via_type)))
```

Where `concept_id` = `clis/<project>/<slug>` (so a re-bucketing changes the
hash) and `resource` = the emitted `file://` URI (or empty).

Deliberately **excludes** `description` (human/LLM-owned, enrichable),
`health_status` (time-varying — would churn the hash on every probe), and
`timestamp` (see below). The hash is the seam between the connector-owned domain
(structure) and the agent-owned domain (prose); `enriched_against`
cross-references it.

**Total ordering is mandatory, not just YAML key sorting (corrected after
review).** The existing query helpers use unordered `select(...).all()`
(`core/catalog/queries.py:30`, `:79`) and edge recompute inserts from a `set`
(`core/graph/edges.py:56`), so iteration order is **not** stable. Byte-stable
re-produce therefore requires the producer to explicitly sort at every level:

- **Concept emission order:** sort CLIs by `concept_id`.
- **Per-concept lists:** `tags`, `ports.in`, `ports.out`, `edges`, and the
  `## Chains into` body links are each sorted (edges/links by `(to_slug,
  via_type)`).
- **YAML:** emitted with sorted keys + sorted scalar lists.
- **`index.md` / `log.md`:** see below.

With those, re-running `okf-produce` over an unchanged catalog rewrites files
**byte-identically** → empty `git diff`. A test asserts this.

**`timestamp` and `log.md` must not break byte-stability (corrected after
review).** A wall-clock value in every produce would defeat the determinism
promise. Therefore:

- A concept's `timestamp` is `Cli.updated_at` (data, changes only when the row
  changes) — never the produce wall-clock.
- `log.md` records the **last structural change**, derived from the max
  `Cli.updated_at` across the bundle, not "now". An unchanged catalog yields an
  unchanged `log.md`. The produce process does not write its own run-time into
  the bundle.
- `index.md` is a deterministic directory listing (sorted concept IDs +
  `okf_version`), no timestamps.

**`enriched_against` carry-forward:** on produce, if a concept already exists in
the target bundle with a `description` + `enriched_against`, those two fields are
preserved (produce never authors descriptions). A downstream agent can compare
`enriched_against` to the current `content_hash` to detect prose gone stale
relative to structure.

---

## 7. Error Handling

- `okf-produce` into a non-empty directory that is **not** a recognizable OKF
  bundle (no `index.md` with `okf_version`) → refuse and exit non-zero; require
  `--force` to override. Never clobber arbitrary files.
- Atomic writes: each concept file via tempfile + `os.replace` (CLAUDE.md
  atomic-write rule).
- `okf-ingest` on malformed frontmatter (missing `---` boundaries) → fail that
  concept loudly, continue the rest, exit non-zero if any concept failed. No
  bare `except Exception` that swallows.
- All warnings/summary go to stderr with counts (produced N concepts; ingested
  M descriptions; skipped K unknown slugs; failed J).

---

## 8. Testing (`tests/test_okf.py`)

| Test | Asserts |
|---|---|
| `produce_is_deterministic_byte_identical_on_rerun` | re-produce over unchanged catalog → identical bytes |
| `content_hash_excludes_description_and_health` | editing description or health does not change `content_hash` |
| `content_hash_changes_on_structural_edit` | changing ports/tags/side_effect/edges/project/path changes the hash |
| `content_hash_changes_on_rebucket_or_path_move` | changing `project` or `path` changes concept_id/resource → hash changes (F4) |
| `produce_is_stable_under_unordered_db_rows` | shuffled `select().all()` / set-ordered edges still produce identical bytes (F3) |
| `log_and_index_have_no_walltime` | re-produce with no catalog change → `log.md`/`index.md` byte-identical (F3) |
| `produce_fails_on_multiple_capabilities_per_cli` | a CLI with >1 Capability row → produce fails loudly (F2) |
| `roundtrip_produce_then_ingest_restores_descriptions` | produce → edit description in bundle → ingest → DB description updated |
| `ingest_never_mutates_structural_fields` | tampering with ports/tags/side_effect in bundle has no DB effect |
| `ingest_does_not_add_db_columns_or_stamp` | ingest writes only `Cli.description`; no `enriched_against` DB write (F6) |
| `ingest_unknown_slug_skipped_with_warning` | unknown concept slug skipped, counted, non-fatal |
| `edges_in_frontmatter_and_body_links_agree` | the `edges:` list and `## Chains into` links derive from the same CliEdge set and match (F5) |
| `ports_are_node_io_not_edges` | `ports` reflect Capability I/O only; not used as graph adjacency (F5) |
| `launch_spec_never_emitted` | no concept contains launch_spec |
| `malformed_frontmatter_fails_loudly` | missing `---` boundary → that concept fails, non-zero exit |
| `bundle_is_valid_okf` | every concept frontmatter parses under the OKF contract; reserved files lack frontmatter |
| `produce_refuses_nonempty_non_bundle_dir_without_force` | safety guard on --out |

Baseline: existing test suite must remain green (no regression). `core/okf/`
is the only module importing the YAML/serialization path for OKF.

---

## 9. Decisions & Open Questions

**Resolved by the codex review (now baked into the spec):**

- **R1 — `enriched_against` storage:** NO new DB column. Bundle-only,
  produce-side carry-forward (§5, §6). Settled.
- **R2 — read boundary:** add `export_rows(session)` returning full `Cli` +
  `Capability` + outbound `CliEdge`, in a stable total order; do not reuse the
  lossy `overview_rows`/`describe_cli` projections (§3). Settled.
- **R3 — determinism:** total ordering at every level + no wall-clock in
  `log.md`/`index.md`/`timestamp`; hash includes `concept_id`/`resource`
  (§6). Settled.
- **R4 — edges:** explicit `edges:` frontmatter + agreeing body links;
  `ports` are node I/O, never adjacency (§4). Settled.
- **R5 — capability multiplicity:** export the one-row-per-CLI invariant; fail
  loudly on >1 (§4). Settled.

**Still open (resolve at plan time):**

1. **YAML emission:** hand-emit the constrained YAML subset we control
   (recommended — zero new deps, guarantees the byte-stability §6 requires, and
   the frontmatter shape is small and fixed) **vs.** add `PyYAML` with explicit
   `sort_keys=True` + a custom list representer. The project today has no YAML
   dep (only `tomli`/`tomllib`). Lean: hand-emit.
2. **Version bump:** new commands + interchange surface → `1.3.0`.
3. **Naming:** commands `okf-produce` / `okf-ingest` (hyphenated, matches the
   okf-skills `<skill>__<command>` convention and the single-positional argparse
   pattern) vs. `okf produce` (two-token, needs argparse changes). Lean:
   hyphenated.

---

## 10. Changelog line (for CHANGELOG.md at implementation)

```
### Added
- `okf-produce` exports the catalog as an Open Knowledge Format (OKF) bundle
  (Markdown + YAML), consumable by okf-viz / okf-mcp / OKFy and any OKF-aware
  agent. Deterministic (byte-stable re-produce). Typed ports + side-effects ride
  as OKF producer extensions; the call-graph survives as an explicit `edges:`
  frontmatter list AND agreeing body Markdown links. launch_spec is never
  emitted.
- `okf-ingest` round-trips LLM/human-enriched descriptions from an OKF bundle
  back into the catalog (descriptions only; structure stays connector-owned).
```
