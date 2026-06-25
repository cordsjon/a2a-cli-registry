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

**Dependency direction:** `core/okf/` depends on `core/catalog/queries`
(reads: `overview_rows`, `cli_graph`, `describe_cli`) and on `core/store` (the
single description write on ingest). Never the reverse. `serve`/MCP/A2A are not
imported and not modified.

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
  in:  [file:pdf]                  # <- Capability.input_types (sorted)
  out: [text]                      # <- Capability.output_types (sorted)
side_effect: none                  # <- Capability.side_effect
confidence: declared               # <- Capability.confidence (declared/inferred)
health: healthy                    # <- Cli.health_status (informational; NEVER ingested)
---
## Capabilities
Reads `file:pdf`, produces `text`. No side effects. (declared)

## Chains into
- [summarize](../_unbucketed/summarize.md "via text")
```

**Dual edge representation (design decision):** every `CliEdge` is rendered
**both** as structured frontmatter (the `ports` block participates in chain
reconstruction) **and** as a Markdown body link under a `## Chains into`
heading, with `via_type` in the link title attribute. Generic OKF consumers
(`get_neighbors`) traverse the body links; OKF-aware consumers and the
registry's own ingest can read the typed ports from frontmatter. Edge links use
relative paths between concept files.

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
- **`enriched_against`:** ingest stamps the concept's current `content_hash`
  as the description's `enriched_against` provenance for the next produce to
  carry forward. (Stored in the bundle on the next produce; not a new DB column
  in v1 — see Open Questions.)

---

## 6. Determinism (`content_hash`)

Each concept's `content_hash` is `sha256:` over a **canonical structural
tuple**:

```
(slug, lang, sorted(intent_tags), sorted(input_types), sorted(output_types),
 side_effect, confidence, sorted(edges as (to_slug, via_type)))
```

Deliberately **excludes** `description` (human/LLM-owned, enrichable) and
`health_status` (time-varying — would churn the hash on every probe). The hash
is the seam between the connector-owned domain (structure) and the agent-owned
domain (prose); `enriched_against` cross-references it.

**Byte-stable output:** YAML is emitted with sorted keys and sorted list
members, so re-running `okf-produce` over an unchanged catalog rewrites files
**byte-identically** → empty `git diff`. This is the OKF determinism promise and
what makes the bundle PR-reviewable.

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
| `content_hash_changes_on_structural_edit` | changing ports/tags/side_effect/edges changes the hash |
| `roundtrip_produce_then_ingest_restores_descriptions` | produce → edit description in bundle → ingest → DB description updated |
| `ingest_never_mutates_structural_fields` | tampering with ports/tags/side_effect in bundle has no DB effect |
| `ingest_unknown_slug_skipped_with_warning` | unknown concept slug skipped, counted, non-fatal |
| `edges_render_as_both_frontmatter_and_body_links` | every CliEdge appears in `ports` graph AND as a body link with via_type |
| `launch_spec_never_emitted` | no concept contains launch_spec |
| `malformed_frontmatter_fails_loudly` | missing `---` boundary → that concept fails, non-zero exit |
| `bundle_is_valid_okf` | every concept frontmatter parses under the OKF contract; reserved files lack frontmatter |
| `produce_refuses_nonempty_non_bundle_dir_without_force` | safety guard on --out |

Baseline: existing test suite must remain green (no regression). `core/okf/`
is the only module importing the YAML/serialization path for OKF.

---

## 9. Open Questions (resolve at plan time)

1. **`enriched_against` storage:** v1 carries it forward from the existing
   bundle file on produce (no DB change). Confirm we do not want a DB column
   for it in v1.
2. **YAML library:** the project already depends on `tomli`/`tomllib` for TOML;
   OKF frontmatter is YAML. Confirm adding `PyYAML` (or `ruamel.yaml` for
   sorted-key stability) as the one new runtime dep, or hand-emit the
   constrained YAML subset we control. (Hand-emit avoids a new dep and
   guarantees byte-stability; PyYAML is simpler but needs explicit `sort_keys`
   + a custom representer for stable lists.)
3. **Version bump:** new commands + interchange surface → `1.3.0`.
4. **Naming:** commands are `okf-produce` / `okf-ingest` to match the
   okf-skills `<skill>__<command>` convention; confirm vs. `okf produce`
   (two-token) given the single-positional argparse pattern.

---

## 10. Changelog line (for CHANGELOG.md at implementation)

```
### Added
- `okf-produce` exports the catalog as an Open Knowledge Format (OKF) bundle
  (Markdown + YAML), consumable by okf-viz / okf-mcp / OKFy and any OKF-aware
  agent. Deterministic (byte-stable re-produce). Typed ports, side-effects, and
  the call-graph survive as OKF producer extensions + body links. launch_spec is
  never emitted.
- `okf-ingest` round-trips LLM/human-enriched descriptions from an OKF bundle
  back into the catalog (descriptions only; structure stays connector-owned).
```
