# Registry Capability Backfill — Design

**Date:** 2026-07-03
**Repo:** `~/projects/a2a-cli-registry`
**Branch:** `feat/capability-backfill`
**Status:** Approved design — ready for implementation plan.

## Goal

Populate `capability.input_types`, `output_types`, `intent_tags`, and `side_effect`
for the registry's Python CLIs by inferring them from each CLI's source, so the
downstream typed-graph features (`plan_cli_chain`, playbook chaining/ranking, and
eventually Phase 4 hybrid retrieval) have real data to operate on. Additionally,
regenerate `cli.description` for every row and add an LLM sanity-check pass so the
final catalog is actually **human-readable**: every row's description + capability
fields together must convey the CLI's purpose, not just contain non-empty strings.

**This is the root-cause fix** that blocked the playbook-corpus and BM25-recall
measurement work: those need a typed, chainable catalog, and the registry today
is a flat name+description catalog — and per a live-data check, `cli.description`
itself is 100% unusable (see next section), not merely thin.

## Context (verified against live data + code)

- **474 CLIs total; 471 are Python with a `path` that resolves to a real file**
  (checked: 471/474 paths are readable `.py`). Static source parsing is viable
  for the overwhelming majority; LLM fallback is for the residue only. **The
  remaining 3 are shell wrappers** (`consigliere-pp-cli`, `hermes-pp-cli`,
  `poster-engine-pp-cli`, all `lang="shell"`) with no source to statically
  parse — capability-type extraction (input/output types, intent tags,
  side_effect) is scoped to the 471 Python rows only, since type extraction has
  no meaning for a bare shell wrapper. **Description regeneration and the
  sanity check cover all 474 rows**, including these 3 — their descriptions are
  equally corrupted (path-like junk) and "every row is human-readable" must
  include them. For these 3, the regenerator falls back to the LLM with just
  `slug` + the wrapper script's shell content (no AST available).
- **Parser framework breakdown (checked, not assumed):** 243 use argparse, 76
  use **Typer** (72 of those with NO argparse/click signal at all — i.e.
  Typer-only), 24 use click, 23 have `add_subparsers`. **Typer was missing from
  the original extractor design** — without Typer support the extractor would
  route 72+ CLIs to LLM fallback, blowing the ~30-CLI fallback cap by 2.5x on
  Typer alone. Typer AST support is now in scope (see Extractor) — this is not
  optional residue-handling, it is 15%+ of the corpus.
- **The capability table is empty of typed data:** 0/474 rows have any
  `input_types` or `output_types`; only 38/474 have `intent_tags`; `side_effect`
  is `unknown` for 436/474. `bucket` is null for all 474. `launch_spec` is
  `{"kind":"python_module","entrypoint":"<slug>","args_schema":{}}` for the 471
  Python rows (entrypoint == slug), but `{"kind":"executable",
  "entrypoint":"<absolute-path>","args_schema":{}}` for the 3 shell rows —
  entrypoint is an absolute path there, NOT the slug. Any tooling that assumes
  `entrypoint == slug` universally will silently mishandle the 3 shell rows.
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
  3. **All 5 new modules MUST use raw `sqlite3`, never SQLModel/ORM reads of
     `Cli`.** Verified: `Cli.not_standalone: bool = False` is a non-Optional
     column in the model; SQLAlchemy selects all mapped columns by default, so
     any `select(Cli)` against the live DB raises `OperationalError: no such
     column: cli.not_standalone`. This applies to every module that reads `cli`
     rows (description regenerator, extractor, fallback, sanity check, writer)
     — none of them may import `core.models.Cli` for reads; use direct SQL
     (`SELECT slug, path, description FROM cli`) instead.
- `side_effect` vocabulary (`core/models.py:32`): `none/writes-fs/network/destructive/unknown`.
- Existing `intent_tags` vocabulary in the data: `build, extract, package, publish,
  download, convert` (6 verbs, 38 rows). New tags stay within a controlled
  expansion of this set (see Extractor).
- **`cli.description` is 100% corrupted, not merely thin** (checked all 474 rows):
  355 are bare file paths (e.g. `'30_SVG-PAINT/scripts/ppv-dashboard.py'`), 113 are
  captured exception/traceback text from what looks like a crashed `--help` probe
  (e.g. `"ModuleNotFoundError: No module named 'portalocker'"`), and the remaining
  6 are other non-purpose junk (usage strings, pip-install hints, internal build
  paths). Zero rows describe what the CLI actually does. Since
  `extract_intent_tags(slug, description, source)` reads `description` as an
  input, this corruption would also degrade intent-tag quality if left as-is —
  so description regeneration is now in scope, sequenced before intent-tag
  extraction (see Architecture).

## Scope

**In scope:** a static extractor (argparse/click AST parse → typed ports + intent
tags + side_effect), an LLM fallback for CLIs static can't resolve, description
regeneration for every `cli.description` row, an LLM sanity-check pass that flags
rows whose description + capability fields don't add up to an understandable
purpose, and a guarded writer (DB backup + `provenance` column + `--dry-run`
default + `--commit` gate).

**Out of scope (unblocked by this, separate follow-on plans):** the playbook
corpus, the BM25 recall harness, Phase 4 vectors, and any re-chaining logic. No
changes to the registry's ops/serving code — this is an offline batch job against
the DB file. Semantic (non-structural) output types remain a `manual` curation
concern (see Extractor trade-off) — the sanity check flags readability gaps, it
does not fix output-type coarseness.

## Architecture

Five new modules under `tools/` (a new dir; offline batch tooling, kept out of
`core/` which is the serving path):

| Module | Responsibility |
|---|---|
| `tools/description_regenerator.py` | Pure. For one CLI (`slug`, `path`, source), generate a 1-2 sentence purpose description via **local Ollama**. Runs FIRST — its output feeds `extract_intent_tags`. |
| `tools/capability_extractor.py` | Pure, read-only. Parse one CLI's source → `{input_types, output_types, intent_tags, side_effect, confidence}`. No DB, no LLM. |
| `tools/capability_llm_fallback.py` | For a CLI static can't resolve, infer the same shape via a **local** Ollama model. Marked `provenance="llm"`. |
| `tools/sanity_check.py` | Read-only. For each row, ask a **local Ollama** model: "given this description + these capability fields, is the CLI's purpose understandable?" → pass/fail + reason. Runs LAST, over the full proposed dataset, before `--commit`. |
| `tools/backfill_capabilities.py` | The only writer. Backup DB, add `provenance` column, dry-run/commit, idempotent per-slug update. Writes `description` alongside capability fields; refuses `--commit` if sanity-check failures exceed a threshold (see Sanity Check). |

### Description regenerator (`description_regenerator.py`)

Runs first in the pipeline, once per CLI, over `(slug, path, source)`:

- `regenerate_description(slug, source) -> str` — sends `slug + a targeted
  extract` to a **local Ollama model**, asking for a single 1-2 sentence
  purpose statement ("what does this CLI do, in plain language"). The extract
  is NOT a fixed first-N-lines slice — sampling showed parser definitions
  (argparse/click/Typer markers) land beyond line 60 in ~50% of files (10/20
  sampled), so a fixed prefix would frequently capture only imports/boilerplate.
  Instead: AST-extract the module docstring (if present), the parser's
  `description=`/`help=` string (argparse) or command `help` (Typer/click), and
  the function signature + docstring of the entrypoint function; concatenate
  those with the first ~20 lines as light context. No access to the old
  `description` value — it is corrupted (path/traceback text) and would only
  bias the model toward repeating garbage.
- Deterministic guards: empty/unreadable source → `"unknown purpose ({slug})"`
  placeholder, `provenance="llm"`, flagged for the sanity check to catch. Never
  crashes on malformed model output.
- This is the ONLY new field written outside `capability` — `cli.description`
  itself is overwritten. **Per-field provenance, not a shared flag:** rather
  than coupling description-protection to `capability.provenance` (which would
  mean a manual capability fix freezes a possibly-bad generated description,
  and vice versa — two independent failure directions tied to one flag), the
  writer adds a SECOND guarded column: `ALTER TABLE capability ADD COLUMN
  description_provenance TEXT`, same column-existence-check pattern as
  `provenance` (see schema-drift note and Guarded writer step 2). A slug can
  then have a `manual` `description_provenance` with an `inferred`
  `provenance` (or the reverse), and each is checked and overwrite-protected
  independently at write time. This is durable DB state, not just a
  proposals-file artifact — the proposals file additionally carries both
  values per row for human review, but the column is the source of truth for
  the writer's overwrite decision.
- Output feeds `extract_intent_tags` downstream — regeneration must run before
  intent-tag extraction, not after, so tags are derived from a real description
  rather than the corrupted one.

### Extractor (`capability_extractor.py`)

Pure functions over a source string (parsed with `ast`):

- `extract_inputs(source) -> list[str]` — from argparse `add_argument(type=...)`
  (`Path`→`path`, `int`→`int`, `float`→`float`, else `str`), click
  `@option/@argument` decorators, **and Typer `@app.command()` function
  signatures** (parameter type annotations `Path`/`int`/`float`/`str`, plus
  `typer.Option()`/`typer.Argument()` defaults) — Typer is 76/471 CLIs (72
  Typer-only), not optional. Also handles `argparse` under an import alias
  (`import argparse as ap`) and `add_subparsers()` by walking each subparser's
  own `add_argument` calls. Plus name heuristics when untyped
  (`--input`/`--file`/`--in-dir`/`--path`→`path`; `--json`→`json`). Untyped param
  present → `str`.
- `extract_outputs(source) -> list[str]` — structural inference from what the CLI
  produces: file writes (`.write_text`, `open(...,"w"/"a")`, `Path.replace`,
  `json.dump`, `shutil.copy`/`move`) → `path` (and `json` for json.dump);
  `print(json.dumps(...))` → `json`; bare `print(...)` with no json → `text`.
  Coarse and lossy by nature (see trade-off).
- `extract_intent_tags(slug, description, source) -> list[str]` — verb extraction
  from slug + **regenerated** description (never the corrupted original — see
  Description regenerator), matched against a fixed vocabulary (`build, extract,
  package, publish, download, convert, analyze, export, sync, validate, generate,
  transform`) so tags stay consistent. No free-text tags.
- `infer_side_effect(source) -> str` — **matches the existing semantics already
  live in `bridge/llm_infer.py:56-67`, not a new definition:** `network` if
  `httpx`/`requests`/`urllib`/`socket`/`aiohttp` imported (network wins even if
  the tool also writes files); `writes-fs` ONLY when the source modifies an
  **input path in place** (writes back to a path read from the same
  argument/variable — e.g. a formatter or in-place sorter), NOT when it merely
  produces a new output file (a converter writing `out.json` from `in.csv` is
  `none`, matching `bridge/llm_infer.py`'s explicit rule and the fact that
  `core/planner/search.py:46-68` prunes inferred non-`none` side effects from
  chains by default — over-tagging `writes-fs` would wrongly hide converters
  from chaining); `none` if neither; else `unknown`. (`destructive` is not
  auto-inferred — too risky to guess; left to `manual`.)
- `extract_capability(cli_row) -> dict` — composes the above; `confidence` is
  `"inferred"` (all backfilled rows are inferred, never `declared`);
  `provenance="static"`. Routes to the LLM fallback when EITHER inputs OR
  outputs come back empty (not only when both are empty) — a CLI with a
  detected input but no detected output (or vice versa) is a partial-failure
  signal, not a complete extraction, and silently keeping a half-empty row
  would hide the gap from the fallback cap and the coverage metric.

**Trade-off (named):** output-type inference is genuinely weak. A script that
writes a file yields `path`, not a semantic type like `EnrichedSvg` — static
analysis cannot recover types the code never declares. So `output_types` will be
structural (`path`/`json`/`text`), and `confidence="inferred"` records that. This
is honest data — strictly better than the empty strings we have now — but it will
not produce the rich CWL types the seed playbook imagines. Those remain a `manual`
curation concern.

### LLM fallback (`capability_llm_fallback.py`)

Invoked when the static extractor returns empty on EITHER input or output types
(unreadable source; an entrypoint with no argparse/click/Typer parser found —
e.g. the 3 non-Python CLIs or a bare `__main__` batch script; or a partial
extraction with only one side populated). Sends `slug + regenerated description
+ the same targeted extract used by the description regenerator` (module
docstring + parser/command help + entrypoint signature — see Description
regenerator; NOT a fixed first-N-lines slice) to a **local Ollama model**
(local-first tenet; token-frugal — static+Typer handles the ~440+ majority).
Returns the same dict shape, `provenance="llm"`, `confidence="inferred"`.
**Cap:** if more than ~30 CLIs need fallback, stop and report — a large
fallback set means the static extractor needs tuning, not brute LLM force.
Malformed model output degrades to empties, never crashes.

### Sanity check (`sanity_check.py`)

Runs last, read-only, over the full proposed dataset (regenerated descriptions +
extracted capabilities, before any DB write):

- **Zero-tolerance mechanical pre-filter, runs before the LLM call:** reject
  immediately (no model call needed) if the regenerated description matches a
  path-like pattern (`re.match(r'^[\w./-]+\.py$')`) or contains
  exception/traceback markers (`Error`, `Traceback`, `Errno`, `Exception`) — the
  exact corruption shapes this plan exists to eliminate. A regenerated
  description that still looks like the old corruption is a hard bug in the
  regenerator, not a borderline case for the LLM to judge.
- `check_row(slug, description, capability) -> {"ok": bool, "reason": str}` — for
  rows that pass the mechanical pre-filter, asks a **local Ollama model**:
  "given this description and these capability fields (input/output types,
  intent tags, side effect), can you tell what this CLI is for and how it fits
  into a pipeline?" Fails closed — ambiguous model output counts as `ok=False`,
  never silently passes.
- Batched over all **474** proposed rows (descriptions are regenerated and
  sanity-checked for all 474, including the 3 shell CLIs — only capability-type
  fields are scoped to the 471 Python rows, see Context); writes
  `sanity_report.jsonl` (slug, ok, reason) alongside `backfill_proposals.jsonl`
  for human review.
- **Threshold:** if more than ~10% of rows fail (~47), `backfill_capabilities.py`
  refuses `--commit` and prints the failures — same "stop and tune" philosophy as
  the LLM-fallback cap. A small failure count is expected and reviewable by a
  human (some CLIs are genuinely terse); a large one means the regenerator or
  extractor needs fixing, not a forced commit.
- Purely additive signal — it never edits rows itself, only flags. Fixing a
  flagged row is either a regenerator/extractor bug (rerun) or a case for manual
  `provenance` override (out of this plan's scope, same as semantic output types).
- **Calibration set (small, fixed, hand-authored):** before running the sanity
  check over the real 474 rows, run it once against ~10 hand-authored
  description+capability pairs covering known-good (clear purpose, correct
  types) and known-bad (path-like description, wrong side_effect, empty
  capability) cases. This is not a benchmark — it's a cheap sanity check ON the
  sanity checker, so a systematically miscalibrated model (e.g. one that always
  says `ok=True`) is caught before it rubber-stamps the real dataset. Log the
  calibration result in the acceptance-gate summary alongside the real pass
  rate — a checker that fails its own calibration set invalidates the ≥90%
  number on the real run.
- **Cost/latency budget (rough, stated once):** up to ~1400 local Ollama calls
  total across all three LLM call sites (regenerator + fallback + sanity check,
  ≤474 rows each). No hard SLA — this is an offline batch job, not a serving
  path — but a `--dry-run` should print elapsed time so repeated
  "stop-and-tune, rerun" cycles (per the fallback cap and sanity threshold) have
  a known cost; if a full pass exceeds ~15 minutes on the dev machine, that's a
  signal to shard the corpus rather than re-run the whole thing each iteration.

### Guarded writer (`backfill_capabilities.py`)

The only component that mutates the DB. A CLI entrypoint:

1. **Backup first** — copy `registry.db` → `registry.db.bak-<gitsha>` atomically
   (tempfile + `Path.replace`) before any write. No backup, no write.
2. **`provenance` and `description_provenance` columns** — `PRAGMA
   table_info(capability)`; add whichever of `provenance TEXT` /
   `description_provenance TEXT` is absent via guarded `ALTER TABLE`. (Cannot
   assume migrations ran — see schema-drift note.) All reads/writes in this
   plan use raw `sqlite3`, never SQLModel — see schema-drift note's ORM-crash
   consequence.
3. **`--dry-run` is the DEFAULT.** Writes all proposed rows (capability fields
   AND regenerated `cli.description`) to `backfill_proposals.jsonl`, runs the
   sanity check, writes `sanity_report.jsonl`, and prints a summary (counts by
   provenance / confidence, per-project coverage, before/after typed-port
   coverage, sanity pass/fail rate). A DB write requires explicit `--commit`.
4. **Sanity-check gate** — `--commit` reads `sanity_report.jsonl` and refuses to
   proceed if the failure rate exceeds ~10% (see Sanity Check). This is a hard
   stop, not a warning: force past it only by re-running after fixing the
   regenerator/extractor, never by a flag that skips the check.
5. **Idempotent per-slug update, independently gated per field** — updates the
   existing `capability` row and `cli.description` for each `cli_slug`, checking
   `capability_provenance` and `description_provenance` separately (see
   Description regenerator): overwrites `description` only when
   `description_provenance` is `static`/`llm`/NULL, overwrites capability fields
   only when `capability_provenance` is `static`/`llm`/NULL. A `manual` on one
   field never blocks refresh of the other. Never inserts a duplicate capability
   row. Single atomic transaction; rollback on any error.

**Safety invariants (CLAUDE.md):** atomic writes, no bare `except`, DB backup
before mutation, dry-run gate, sanity-check gate, provenance for traceability +
reversibility. The `.bak-<gitsha>` file is the rollback path.

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
| Typer command | `@app.command()` fn with `path: Path` param | `input_types` ⊇ `path` |
| Typer-only, no argparse/click | full Typer CLI fixture | extractor finds a parser, does NOT route to fallback |
| argparse alias | `import argparse as ap; ap.ArgumentParser()` | extractor still detects it |
| subparsers | `add_subparsers()` + per-subcommand `add_argument` | inputs collected from subparser too |
| output file write | `Path(x).write_text(...)` | `output_types` ⊇ `path` |
| output json stdout | `print(json.dumps(d))` | ⊇ `json` |
| intent tags | slug `svg-export`, regenerated desc "publish to Etsy" | tags ⊇ `{export, publish}`, vocab-constrained |
| side_effect network | `import httpx` | `network` |
| side_effect in-place write | `open(same_input_path, "w")` after reading it | `writes-fs` |
| side_effect new-output-file | `open("out.json", "w")` (new file, not the input) | `none` (NOT `writes-fs` — matches `bridge/llm_infer.py` semantics) |
| partial extraction | input detected, output empty (or reverse) | routes to fallback (not silently kept as a half-empty static row) |
| empty source | `""` | all empty → routes to fallback |

**`tests/test_capability_llm_fallback.py`** — the Ollama call is a monkeypatched
seam: assert JSON parsed into the right shape, `provenance="llm"`, malformed output
→ empties (no crash).

**`tests/test_description_regenerator.py`** — Ollama call monkeypatched: (1)
normal source → non-empty 1-2 sentence description, old corrupted description
never passed to the model; (2) empty/unreadable source → placeholder string,
never crashes; (3) malformed model output → placeholder, not an exception.

**`tests/test_sanity_check.py`** — Ollama call monkeypatched: (1) coherent
description+capability → `ok=True`; (2) path-like or traceback-like description
→ `ok=False` rejected by the MECHANICAL pre-filter, Ollama never called; (3)
mismatched/garbage input that isn't path/traceback-shaped → `ok=False` via the
LLM with a reason; (4) ambiguous/malformed model output → `ok=False` (fails
closed, never defaults to True).

**`tests/test_backfill_capabilities.py`** (temp `registry.db`, built with raw
`sqlite3.executescript` — NOT `SQLModel.metadata.create_all` — so the fixture
matches the live schema-drift condition, i.e. the temp DB's `cli` table also
lacks `not_standalone`, same as production): (1) `--dry-run` writes proposals +
sanity report + ZERO DB changes; (2) `--commit` updates capability rows AND
`cli.description` + creates `.bak`; (3) re-run does not clobber a slug whose
`provenance` is `manual` (capability protected) independently from one whose
`description_provenance` is `manual` (description protected) — assert each can
be manual while the other stays `inferred` and gets refreshed; (4) backup
failure aborts the write; (5) BOTH `provenance` and `description_provenance`
columns auto-added when missing; (6) `--commit` refuses to proceed when
sanity-check failure rate exceeds threshold; (7) `--commit` proceeds when
failure rate is under threshold; (8) all 474 rows (including the 3 shell CLIs)
get a description proposal; only the 471 Python rows get capability-field
proposals; (9) every module's DB access uses raw `sqlite3` — a regression test
asserts no module imports `core.models.Cli` for a read path (grep-based or
`ast`-based import check), so the ORM-crash risk can't silently reappear.

**Acceptance gate:** after `--commit`, typed-port coverage (capability fields,
scoped to the 471 Python rows) jumps from 0/474 toward ~440+/471, verifiable by
a one-line query, AND sanity-check pass rate (descriptions, scoped to ALL 474
rows including the 3 shell CLIs) is ≥90%. Both numbers are the deliverable —
coverage unblocks downstream typed-chaining features, sanity rate is the
evidence that "readable and makes sense" was actually achieved, for every row,
rather than merely non-empty. The proposals + sanity report files let a human
eyeball fidelity and remaining failures before trusting the result.

## Out of scope (future, unblocked by this)

- Playbook corpus authored over the now-typed CLIs.
- BM25 recall harness + measurement (the Phase-4 precondition).
- Phase 4 hybrid vector retrieval (decide AFTER measuring BM25 on the typed corpus).
- Semantic (non-structural) output types — a `manual` curation pass.
- Migrating the live DB schema up to the full model (`not_standalone` etc.) — a
  separate concern; this plan only adds `provenance`.
- Fixing individual rows flagged by the sanity check beyond what the
  regenerator/extractor can do automatically — persistent failures after tuning
  become a `manual` curation backlog item, not a blocker for this plan's commit.

## Codex review — pre-panel

_Generated by solo `codex exec` (duo-review Gemini leg unavailable — free-tier "Gemini Code Assist for individuals" is deprecated, account requires migration to Antigravity; solo fallback is sanctioned by protocol when duo is unavailable). Append-only per feedback_codex_spec_review_protocol — nothing above this section was altered by Codex._

### [CRITICAL] `description_provenance` has no durable storage
- What: The spec requires independent manual overwrite protection for descriptions, but defines only `capability.provenance` and no actual `description_provenance` column/storage.
- Where: lines 126-130, "This needs no new DB column … `description_provenance` value co-located in the same `capability` row"; writer section adds only `provenance TEXT` but later checks `capability_provenance` and `description_provenance` separately.
- Why it matters: Implementers cannot reliably preserve a manual description independently from a manual capability; the proposed idempotency/overwrite rules are not implementable against the live `capability` schema.
- Suggested fix: Define explicit durable storage, e.g. guarded `ALTER TABLE capability ADD COLUMN description_provenance TEXT`, or make `provenance` a documented structured JSON field and update all read/write/test semantics accordingly.
- Confidence: high

### [IMPORTANT] SQLModel reads of `Cli` fail on the live DB
- What: The spec notes `cli.not_standalone` is missing but omits that any SQLModel `select(Cli)` against `registry.db` currently fails with `no such column: cli.not_standalone`.
- Where: Schema-drift note lists only two consequences of the missing column; Out-of-scope section keeps migrating `not_standalone` out of scope without naming this crash risk.
- Why it matters: Offline tools that reuse `core.store.db.init_db` and `core.models.Cli` to enumerate rows will crash before dry-run or commit.
- Suggested fix: Require raw SQLite access with explicit existing columns for this batch job, or add a guarded `cli.not_standalone BOOLEAN NOT NULL DEFAULT 0` migration before any ORM use.
- Confidence: high

### [IMPORTANT] 471-row sanity scope conflicts with "every row"
- What: The spec promises regenerated descriptions for every row, but later sanity-checks only "all 471 proposed rows" while the live DB has 474 rows and the 3 non-Python rows also have path-like junk descriptions.
- Where: Goal says regenerate `cli.description` for every row; Sanity check section says "Batched over all 471 proposed rows"; Acceptance gate uses `0/474` and `~440+/471`.
- Why it matters: The three shell/executable rows can remain corrupted while the acceptance gate still passes.
- Suggested fix: Make row scope explicit: either generate/sanity-check descriptions for all 474 rows, or state that the 3 shell rows are excluded and remove "every row" language.
- Confidence: high

### [NIT] `launch_spec` entrypoint claim is false for executable rows
- What: The spec says `launch_spec` is uniformly `{"kind":"python_module"|"executable","entrypoint":"<slug>","args_schema":{}}`, but the 3 executable rows use absolute file paths as `entrypoint`.
- Where: Context section, quoted phrase `entrypoint":"<slug>"`.
- Why it matters: Low implementation risk unless tooling assumes `entrypoint == slug`, but it is a live-data grounding error.
- Suggested fix: Say Python-module rows use slug entrypoints; executable rows use absolute executable paths.
- Confidence: high

### Self-flagged uncertainty
- Parser framework counts are close but depend on the exact detector; Typer/click count variance not treated as a finding because the design already addresses the known Typer gap.
- The SQLModel failure only matters if the new tools use ORM models; the spec does not explicitly say they will, but it also does not forbid it.
- The intended treatment of the 3 shell CLIs may be "description-only," but the current spec mixes "every row," "3 non-Python fallback," and "471 proposed rows."

### Claude's triage (per-comment, per protocol)

1. **CRITICAL `description_provenance` storage — ✅ VALID, applying fix.** Codex is right: my prior fix for the provenance-coupling finding named a field (`description_provenance`) without ever defining where it lives. Fixing now: add a real guarded column, same pattern as `provenance`.
2. **IMPORTANT SQLModel/ORM crash — ✅ VALID, applying fix.** Confirmed independently: `Cli.not_standalone: bool = False` has no `Optional`, live table lacks the column, any `select(Cli)` raises `OperationalError`. Adding an explicit raw-sqlite3 constraint to the spec.
3. **IMPORTANT 471-vs-474 scope gap — ✅ VALID, applying fix.** Confirmed independently: the 3 shell CLIs (`consigliere-pp-cli`, `hermes-pp-cli`, `poster-engine-pp-cli`) have path-like descriptions too and would fall through every count in the spec. Making scope explicit: all 474 get description regeneration + sanity check; only capability-type extraction is bounded to the 471 Python-resolvable rows (extraction has no meaning for a bare shell wrapper).
4. **NIT launch_spec entrypoint claim — ✅ VALID, applying fix.** Confirmed independently via query. Correcting the claim.
