You are GEMINI, an independent reviewer.

You are one of TWO reviewers performing an independent review of the spec.
You will NEVER see the other reviewer's findings — your report stands on its own.
Claude will read both reports and triage per-comment.

Phase: pre-panel
Spec: /Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-03-capability-backfill-design.md

Use ONLY the bundle you are given (CONTEXT.md + SPEC.md). Do not re-explore the repo —
the context collector already did that and noted gaps in section 7. If something you
would want to verify is missing from the context, flag it explicitly rather than guess.

Output structure (markdown, to stdout):

## Findings — <your name>

For each finding:

### [SEVERITY] short title
- What: the issue in one sentence
- Where: spec section, line, or quoted phrase
- Why it matters: the consequence if shipped as-is
- Suggested fix: concrete change, not a vague direction
- Confidence: high | medium | low

SEVERITY in { CRITICAL, IMPORTANT, NIT }
- CRITICAL — wrong premise, broken cross-reference, will cause rework or incident
- IMPORTANT — design weakness, missing scope, ambiguous decision
- NIT — wording, typo, minor inconsistency

At the end:

## Self-flagged uncertainty
Bullet list of points where you have low confidence — Claude will weigh these against
the other reviewer's report if they cover overlapping ground.

Constraints:
- Append-only. Do not propose edits to the spec text directly.
- Cite line numbers or quoted phrases for every finding.
- If you have zero findings in a severity, write (none) — do not pad.
- Disagree freely with what you would expect a co-reviewer to say. Independence is
  the entire point of running two of you.

BUNDLE:

# DUO REVIEW BUNDLE

## CONTEXT.md (collected by gemini, phase 0)

# CONTEXT — 2026-07-03-capability-backfill-design

_Generated procedurally by phase0-procedural.sh at 2026-07-03T07:16:37Z.
No LLM call — pure grep + stat. Reviewers can request deeper context on demand._

## 1. Spec under review

- **Path:** `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-03-capability-backfill-design.md`
- **Last modified:** 2026-07-03 09:16:09
- **Lines:** 330
- **Bytes:** 21528
- **Project root:** `/Users/jcords-macmini/projects/a2a-cli-registry`

### Section index

- Goal
- Context (verified against live data + code)
- Scope
- Architecture
- Testing
- Out of scope (future, unblocked by this)

## 2. Cited artifacts — grounded existence checks

This is the **grounding layer**. Every citation extracted from the spec was checked
against the filesystem. `OK` = path exists, `MISSING` = does not exist, `GLOB` =
matches via shell glob (count > 0).

### 2.1 Tilde paths

| Path | Status | Size / kind |
|---|---|---|
| `~/projects/a2a-cli-registry` | OK | directory, 27 entries |

### 2.2 Backticked filenames

| Filename | Status | Locations (up to 3) |
|---|---|---|
| `backfill_capabilities.py` | MISSING | — |
| `backfill_proposals.jsonl` | MISSING | — |
| `bridge/llm_infer.py` | OK | ~/projects/a2a-cli-registry/bridge/llm_infer.py |
| `capability_extractor.py` | MISSING | — |
| `capability_llm_fallback.py` | MISSING | — |
| `core/playbooks/signature.py` | OK | ~/projects/a2a-cli-registry/core/playbooks/signature.py |
| `description_regenerator.py` | MISSING | — |
| `out.json` | MISSING | — |
| `sanity_check.py` | MISSING | — |
| `sanity_report.jsonl` | MISSING | — |
| `tests/test_backfill_capabilities.py` | MISSING | — |
| `tests/test_capability_extractor.py` | MISSING | — |
| `tests/test_capability_llm_fallback.py` | MISSING | — |
| `tests/test_description_regenerator.py` | MISSING | — |
| `tests/test_sanity_check.py` | MISSING | — |
| `tools/backfill_capabilities.py` | MISSING | — |
| `tools/capability_extractor.py` | MISSING | — |
| `tools/capability_llm_fallback.py` | MISSING | — |
| `tools/description_regenerator.py` | MISSING | — |
| `tools/sanity_check.py` | MISSING | — |

### 2.3 Slash-commands (skills)

| Command | Status | Path |
|---|---|---|

### 2.4 sh: panel skills

| Skill | Status | Path |
|---|---|---|

## 3-6. Surrounding code, prior decisions, open questions, repo conventions

**Procedurally deferred.** This collector intentionally does not synthesize these
sections — they require judgment the grounding layer alone cannot provide.
Reviewers should pull what they need:

- For *surrounding code* of a flagged path: open the path directly.
- For *prior decisions*: check sibling specs in `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs` (see section index).
- For *open questions inherited*: search the spec for "Q1", "Q2", etc.
- For *repo conventions*: read `/Users/jcords-macmini/projects/a2a-cli-registry/CLAUDE.md` and `/Users/jcords-macmini/projects/a2a-cli-registry/KNOWN_PATTERNS.md`.

## 7. What this collector did NOT check

- Function names, CLI sub-commands, and config keys (`escalation.to`, `schema_version` etc.) — these are spec-internal JSON schema fields, not external artifacts; no existence check applies.
- External URLs and resources.
- Path placeholders containing `<...>` or `...` — filtered out as noise.
- Whether file *contents* match the spec's claims about them. Only file existence is verified.
- Imports / call sites of cited code paths (would require an LSP or wider grep).

If a reviewer needs any of these, they should request explicitly.

## SPEC.md (/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-03-capability-backfill-design.md)

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
  for the overwhelming majority; LLM fallback is for the residue only.
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
  writer tracks provenance for both fields in the `backfill_proposals.jsonl`
  record (`{slug, capability_provenance, description_provenance}`) and reads
  BOTH independently at write time: a slug can have a `manual` description with
  an `inferred` capability (or the reverse), and each is overwrite-protected on
  its own. This needs no new DB column — the per-field state lives in the
  proposals file's history plus a lightweight `description_provenance` value
  co-located in the same `capability` row (reusing the existing free-form
  storage rather than adding a column now; a real column is a 1-line follow-up
  if this file-based tracking proves awkward in practice).
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
- Batched over all 471 proposed rows; writes `sanity_report.jsonl` (slug, ok,
  reason) alongside `backfill_proposals.jsonl` for human review.
- **Threshold:** if more than ~10% of rows fail (~47), `backfill_capabilities.py`
  refuses `--commit` and prints the failures — same "stop and tune" philosophy as
  the LLM-fallback cap. A small failure count is expected and reviewable by a
  human (some CLIs are genuinely terse); a large one means the regenerator or
  extractor needs fixing, not a forced commit.
- Purely additive signal — it never edits rows itself, only flags. Fixing a
  flagged row is either a regenerator/extractor bug (rerun) or a case for manual
  `provenance` override (out of this plan's scope, same as semantic output types).

### Guarded writer (`backfill_capabilities.py`)

The only component that mutates the DB. A CLI entrypoint:

1. **Backup first** — copy `registry.db` → `registry.db.bak-<gitsha>` atomically
   (tempfile + `Path.replace`) before any write. No backup, no write.
2. **`provenance` column** — `PRAGMA table_info(capability)`; if `provenance`
   absent, `ALTER TABLE capability ADD COLUMN provenance TEXT`. (Cannot assume
   migrations ran — see schema-drift note.)
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

**`tests/test_backfill_capabilities.py`** (temp `registry.db`): (1) `--dry-run`
writes proposals + sanity report + ZERO DB changes; (2) `--commit` updates
capability rows AND `cli.description` + creates `.bak`; (3) re-run does not
clobber a `manual`-provenance row; (4) backup failure aborts the write; (5)
`provenance` column auto-added when missing; (6) `--commit` refuses to proceed
when sanity-check failure rate exceeds threshold; (7) `--commit` proceeds when
failure rate is under threshold.

**Acceptance gate:** after `--commit`, typed-port coverage jumps from 0/474 toward
~440+/471, verifiable by a one-line query, AND sanity-check pass rate is ≥90% of
proposed rows. Both numbers are the deliverable — coverage unblocks downstream
typed-chaining features, sanity rate is the evidence that "readable and makes
sense" was actually achieved rather than merely non-empty. The proposals + sanity
report files let a human eyeball fidelity and remaining failures before trusting
the result.

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
