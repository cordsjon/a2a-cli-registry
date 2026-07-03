# Registry Capability Backfill — Design

**Date:** 2026-07-03
**Repo:** `~/projects/a2a-cli-registry`
**Branch:** `feat/capability-backfill`
**Status:** Approved design — ready for implementation plan.

## Goal

Populate `capability.input_types`, `output_types`, `intent_tags`, and `side_effect`
for the registry's Python CLIs by inferring them from each CLI's source, so the
downstream typed-graph features (`plan_cli_chain`, playbook chaining/ranking, and
eventually Phase 4 hybrid retrieval) have real data to operate on.

**This is the root-cause fix** that blocked the playbook-corpus and BM25-recall
measurement work: those need a typed, chainable catalog, and the registry today
is a flat name+description catalog.

## Context (verified against live data + code)

- **474 CLIs total; 471 are Python with a `path` that resolves to a real file**
  (checked: 471/474 paths are readable `.py`). Static source parsing is viable
  for the overwhelming majority; LLM fallback is for the residue only.
- **The capability table is empty of typed data:** 0/474 rows have any
  `input_types` or `output_types`; only 38/474 have `intent_tags`; `side_effect`
  is `unknown` for 436/474. `bucket` is null for all 474. `launch_spec` is
  uniformly `{"kind":"python_module"|"executable","entrypoint":"<slug>","args_schema":{}}`.
- **Fields are CSV strings, not JSON arrays.** `Capability.input_types` etc. are
  `""`-default CSV (`core/models.py:29-32`), and existing code splits on `,`
  (`core/playbooks/signature.py`). The writer MUST emit CSV, not JSON.
- **A `confidence` column already exists** (`core/models.py:33`), vocabulary
  `declared`/`inferred`. Backfilled rows use `inferred`. Do NOT invent a second
  confidence field — reuse this one; add a separate `provenance` column for the
  static-vs-llm-vs-manual source.
- **Schema drift: the live `registry.db` is behind the model.** The DB's `cli`
  table has NO `not_standalone` column (present in `core/models.py:17` but never
  migrated — `SQLModel.metadata.create_all` at `core/store/db.py:22` only adds
  new *tables*, never alters existing ones). Consequences:
  1. The writer must `ALTER TABLE capability ADD COLUMN provenance` guarded by a
     column-existence check (cannot assume migrations ran).
  2. The extractor cannot use `not_standalone` to skip non-CLIs on the live DB —
     it must detect "no argparse/click parser found" itself.
- `side_effect` vocabulary (`core/models.py:32`): `none/writes-fs/network/destructive/unknown`.
- Existing `intent_tags` vocabulary in the data: `build, extract, package, publish,
  download, convert` (6 verbs, 38 rows). New tags stay within a controlled
  expansion of this set (see Extractor).

## Scope

**In scope:** a static extractor (argparse/click AST parse → typed ports + intent
tags + side_effect), an LLM fallback for CLIs static can't resolve, and a guarded
writer (DB backup + `provenance` column + `--dry-run` default + `--commit` gate).

**Out of scope (unblocked by this, separate follow-on plans):** the playbook
corpus, the BM25 recall harness, Phase 4 vectors, and any re-chaining logic. No
changes to the registry's ops/serving code — this is an offline batch job against
the DB file.

## Architecture

Three new modules under `tools/` (a new dir; offline batch tooling, kept out of
`core/` which is the serving path):

| Module | Responsibility |
|---|---|
| `tools/capability_extractor.py` | Pure, read-only. Parse one CLI's source → `{input_types, output_types, intent_tags, side_effect, confidence}`. No DB, no LLM. |
| `tools/capability_llm_fallback.py` | For a CLI static can't resolve, infer the same shape via a **local** Ollama model. Marked `provenance="llm"`. |
| `tools/backfill_capabilities.py` | The only writer. Backup DB, add `provenance` column, dry-run/commit, idempotent per-slug update. |

### Extractor (`capability_extractor.py`)

Pure functions over a source string (parsed with `ast`):

- `extract_inputs(source) -> list[str]` — from argparse `add_argument(type=...)`
  (`Path`→`path`, `int`→`int`, `float`→`float`, else `str`) and click
  `@option/@argument` decorators; plus name heuristics when untyped
  (`--input`/`--file`/`--in-dir`/`--path`→`path`; `--json`→`json`). Untyped param
  present → `str`.
- `extract_outputs(source) -> list[str]` — structural inference from what the CLI
  produces: file writes (`.write_text`, `open(...,"w"/"a")`, `Path.replace`,
  `json.dump`) → `path` (and `json` for json.dump); `print(json.dumps(...))` →
  `json`. Coarse and lossy by nature (see trade-off).
- `extract_intent_tags(slug, description, source) -> list[str]` — verb extraction
  from slug + description, matched against a fixed vocabulary
  (`build, extract, package, publish, download, convert, analyze, export, sync,
  validate, generate, transform`) so tags stay consistent. No free-text tags.
- `infer_side_effect(source) -> str` — `network` if `httpx`/`requests`/`urllib`/
  `socket` imported; `writes-fs` if a file write detected; `none` if neither; else
  `unknown`. (`destructive` is not auto-inferred — too risky to guess; left to
  `manual`.)
- `extract_capability(cli_row) -> dict` — composes the above; `confidence` is
  `"inferred"` (all backfilled rows are inferred, never `declared`);
  `provenance="static"`. If BOTH inputs and outputs come back empty, the caller
  routes this CLI to the LLM fallback.

**Trade-off (named):** output-type inference is genuinely weak. A script that
writes a file yields `path`, not a semantic type like `EnrichedSvg` — static
analysis cannot recover types the code never declares. So `output_types` will be
structural (`path`/`json`/`text`), and `confidence="inferred"` records that. This
is honest data — strictly better than the empty strings we have now — but it will
not produce the rich CWL types the seed playbook imagines. Those remain a `manual`
curation concern.

### LLM fallback (`capability_llm_fallback.py`)

Invoked only when the static extractor returns empty on both input and output
types (unreadable source, or an entrypoint with no argparse/click — e.g. the 3
non-Python CLIs or a bare `__main__` batch script). Sends `slug + description +
first ~60 lines of source` to a **local Ollama model** (local-first tenet;
token-frugal — static handles the ~440+ majority). Returns the same dict shape,
`provenance="llm"`, `confidence="inferred"`. **Cap:** if more than ~30 CLIs need
fallback, stop and report — a large fallback set means the static extractor needs
tuning, not brute LLM force. Malformed model output degrades to empties, never
crashes.

### Guarded writer (`backfill_capabilities.py`)

The only component that mutates the DB. A CLI entrypoint:

1. **Backup first** — copy `registry.db` → `registry.db.bak-<gitsha>` atomically
   (tempfile + `Path.replace`) before any write. No backup, no write.
2. **`provenance` column** — `PRAGMA table_info(capability)`; if `provenance`
   absent, `ALTER TABLE capability ADD COLUMN provenance TEXT`. (Cannot assume
   migrations ran — see schema-drift note.)
3. **`--dry-run` is the DEFAULT.** Writes all proposed rows to
   `backfill_proposals.jsonl` and prints a summary (counts by provenance /
   confidence, per-project coverage, before/after typed-port coverage). A DB write
   requires explicit `--commit`.
4. **Idempotent per-slug update** — updates the existing capability row for each
   `cli_slug` (never inserts a duplicate). Overwrites only rows whose current
   `provenance` is `static`/`llm`/NULL; NEVER clobbers a `manual`-provenance row
   (human corrections win). Single atomic transaction; rollback on any error.

**Safety invariants (CLAUDE.md):** atomic writes, no bare `except`, DB backup
before mutation, dry-run gate, provenance for traceability + reversibility. The
`.bak-<gitsha>` file is the rollback path.

## Testing

Unit tests over source-string fixtures (no live DB, no live LLM); one integration
test for the writer against a temp DB.

**`tests/test_capability_extractor.py`** (the bulk):

| Test | Fixture | Asserts |
|---|---|---|
| argparse type=Path | `add_argument("--in", type=Path)` | `input_types` ⊇ `path` |
| argparse type=int | `add_argument("--n", type=int)` | ⊇ `int` |
| name heuristic | `add_argument("--input-file")` untyped | `path`, confidence `inferred` |
| click option | `@click.option("--out", type=click.Path())` | `path` |
| output file write | `Path(x).write_text(...)` | `output_types` ⊇ `path` |
| output json stdout | `print(json.dumps(d))` | ⊇ `json` |
| intent tags | slug `svg-export`, desc "publish to Etsy" | tags ⊇ `{export, publish}`, vocab-constrained |
| side_effect network | `import httpx` | `network` |
| side_effect writes | `open(p, "w")` | `writes-fs` |
| empty source | `""` | all empty → routes to fallback |

**`tests/test_capability_llm_fallback.py`** — the Ollama call is a monkeypatched
seam: assert JSON parsed into the right shape, `provenance="llm"`, malformed output
→ empties (no crash).

**`tests/test_backfill_capabilities.py`** (temp `registry.db`): (1) `--dry-run`
writes proposals + ZERO DB changes; (2) `--commit` updates rows + creates `.bak`;
(3) re-run does not clobber a `manual`-provenance row; (4) backup failure aborts
the write; (5) `provenance` column auto-added when missing.

**Acceptance gate:** after `--commit`, typed-port coverage jumps from 0/474 toward
~440+/471, verifiable by a one-line query. The proposals file lets a human eyeball
fidelity before trusting it. That coverage number is the deliverable — it unblocks
every downstream feature.

## Out of scope (future, unblocked by this)

- Playbook corpus authored over the now-typed CLIs.
- BM25 recall harness + measurement (the Phase-4 precondition).
- Phase 4 hybrid vector retrieval (decide AFTER measuring BM25 on the typed corpus).
- Semantic (non-structural) output types — a `manual` curation pass.
- Migrating the live DB schema up to the full model (`not_standalone` etc.) — a
  separate concern; this plan only adds `provenance`.
