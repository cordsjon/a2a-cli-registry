# DUO REVIEW BUNDLE

## CONTEXT.md (procedural extraction, phase 0)

# CONTEXT — 2026-10-18-capability-map-phase0

_Generated procedurally by phase0-procedural.sh at 2026-10-18T18:26:00Z.
No LLM call — pure grep + stat. Reviewers can request deeper context on demand._

## 1. Spec under review

- **Path:** `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/plans/2026-10-18-capability-map-phase0.md`
- **Last modified:** 2026-10-18 19:32:50
- **Lines:** 469
- **Bytes:** 34233
- **Project root:** `/Users/jcords-macmini/projects/a2a-cli-registry`

### Section index

- Hierarchy
- Global Constraints
- Review Focus
- Baseline (recorded at execution, Task 1 Step 3)
- Self-review notes

## 2. Cited artifacts — grounded existence checks

This is the **grounding layer**. Every citation extracted from the spec was checked
against the filesystem. `OK` = path exists, `MISSING` = does not exist, `GLOB` =
matches via shell glob (count > 0).

### 2.1 Tilde paths

| Path | Status | Size / kind |
|---|---|---|
| `~/.config/git/hooks/pre-commit` | OK | file, 3037B |
| `~/.hermes/cli-registry.db` | OK | file, 733184B |
| `~/.hermes/cli-registry.db.bak-$(git` | MISSING | — |
| `~/.hermes/cli-registry.db?` | MISSING | — |
| `~/.local/state/a2a-cli-registry` | MISSING | — |
| `~/.local/state/a2a-cli-registry/backfill-dryrun-` | MISSING | — |
| `~/.local/state/a2a-cli-registry/backfill-dryrun-$(date` | MISSING | — |
| `~/.local/state/a2a-cli-registry/backfill-dryrun-*.log` | MISSING | — |
| `~/projects/00_Governance` | OK | directory, 2735 entries |
| `~/projects/00_Governance/bin/foundations` | OK | file, 508B |
| `~/projects/00_Governance/scripts/register_cli.py:181` | MISSING | — |
| `~/projects/20_CONSIGLIERE/FOUNDATIONS.md` | OK | file, 1232B |
| `~/projects/20_CONSIGLIERE/docs/superpowers/specs/2026-10-18-capability-consolidation-design.md` | OK | file, 18096B |
| `~/projects/a2a-cli-registry` | OK | directory, 36 entries |
| `~/projects/a2a-cli-registry;` | MISSING | — |

### 2.2 Backticked filenames

| Filename | Status | Locations (up to 3) |
|---|---|---|
| `BACKLOG.md` | OK | ~/projects/a2a-cli-registry/BACKLOG.md |
| `DECISIONS.md` | OK | ~/projects/a2a-cli-registry/DECISIONS.md;~/.claude/skills/DECISIONS.md |
| `FOUNDATIONS.md` | MISSING | — |
| `backfill_proposals.jsonl` | OK | ~/projects/a2a-cli-registry/backfill_proposals.jsonl |
| `core/models.py` | OK | ~/projects/a2a-cli-registry/core/models.py |
| `core/populate.py` | OK | ~/projects/a2a-cli-registry/core/populate.py |
| `docs/superpowers/plans/2026-07-03-capability-backfill.md` | OK | ~/projects/a2a-cli-registry/docs/superpowers/plans/2026-07-03-capability-backfill.md |
| `docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md` | OK | ~/projects/a2a-cli-registry/docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md |
| `register_cli.py` | MISSING | — |
| `sanity_report.jsonl` | OK | ~/projects/a2a-cli-registry/sanity_report.jsonl |
| `tests/conftest.py` | OK | ~/projects/a2a-cli-registry/demo/.sandbox/venv-streamlit/lib/python3.13/site-packages/pyarrow/tests/conftest.py;~/projects/a2a-cli-registry/tests/conftest.py |
| `tests/test_backfill_capabilities.py` | OK | ~/projects/a2a-cli-registry/tests/test_backfill_capabilities.py |
| `tests/test_catalog.py` | OK | ~/projects/a2a-cli-registry/tests/test_catalog.py |
| `tests/test_populate.py` | OK | ~/projects/a2a-cli-registry/tests/test_populate.py |
| `tests/test_sanity_check.py` | OK | ~/projects/a2a-cli-registry/tests/test_sanity_check.py |
| `tests/test_server_overview.py` | OK | ~/projects/a2a-cli-registry/tests/test_server_overview.py |
| `tests/test_web_overview_view.py` | OK | ~/projects/a2a-cli-registry/tests/test_web_overview_view.py |
| `tools/backfill_capabilities.py` | OK | ~/projects/a2a-cli-registry/tools/backfill_capabilities.py |
| `tools/capability_extractor.py` | OK | ~/projects/a2a-cli-registry/tools/capability_extractor.py |
| `tools/capability_llm_fallback.py` | OK | ~/projects/a2a-cli-registry/tools/capability_llm_fallback.py |
| `tools/capability_repair.py` | OK | ~/projects/a2a-cli-registry/tools/capability_repair.py |
| `tools/description_regenerator.py` | OK | ~/projects/a2a-cli-registry/tools/description_regenerator.py |
| `tools/sanity_check.py` | OK | ~/projects/a2a-cli-registry/tools/sanity_check.py |

### 2.3 Slash-commands (skills)

| Command | Status | Path |
|---|---|---|
| `/overview` | MISSING | — |

### 2.4 sh: panel skills

| Skill | Status | Path |
|---|---|---|
| `sh:architecture-panel` | OK | ~/.claude/commands/sh/architecture-panel.md |
| `sh:spec-panel` | OK | ~/.claude/commands/sh/spec-panel.md |

## 3-6. Surrounding code, prior decisions, open questions, repo conventions

**Procedurally deferred.** This collector intentionally does not synthesize these
sections — they require judgment the grounding layer alone cannot provide.
Reviewers should pull what they need:

- For *surrounding code* of a flagged path: open the path directly.
- For *prior decisions*: check sibling specs in `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/plans` (see section index).
- For *open questions inherited*: search the spec for "Q1", "Q2", etc.
- For *repo conventions*: read `/Users/jcords-macmini/projects/a2a-cli-registry/CLAUDE.md` and `/Users/jcords-macmini/projects/a2a-cli-registry/KNOWN_PATTERNS.md`.

## 7. What this collector did NOT check

- Function names, CLI sub-commands, and config keys (`escalation.to`, `schema_version` etc.) — these are spec-internal JSON schema fields, not external artifacts; no existence check applies.
- External URLs and resources.
- Path placeholders containing `<...>` or `...` — filtered out as noise.
- Whether file *contents* match the spec's claims about them. Only file existence is verified.
- Imports / call sites of cited code paths (would require an LSP or wider grep).

If a reviewer needs any of these, they should request explicitly.

## SPEC.md (/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/plans/2026-10-18-capability-map-phase0.md)

# Capability Map Phase 0 Implementation Plan

**Status 2026-10-18 19:30 (operator ruling, 20_CONSIGLIERE DECISIONS Q92): NOT cleared for execution.** This plan was written before the operator ruled "spec → architecture review → LLM panel → plans" for the capability-consolidation design. It goes through `sh:architecture-panel`, then `sh:spec-panel`, then a Codex review, and only then to execution. Do not start Task 1 until all three are recorded here with their verdicts.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every enabled CLI in the live registry a prose "can do" description and a sanity-checked capability row, by executing the already-built backfill pipeline against `~/.hermes/cli-registry.db` behind the operator gate the design names.

**Architecture:** The pipeline exists. Tasks 1 to 6 of `docs/superpowers/plans/2026-07-03-capability-backfill.md` shipped in July (commits `e5c0129` through `c825cf1`: `tools/description_regenerator.py`, `tools/capability_extractor.py`, `tools/capability_llm_fallback.py`, `tools/sanity_check.py`, `tools/capability_repair.py`, `tools/backfill_capabilities.py`; 96 tests green on 2026-10-18). Its Task 7 dry run ran once against a 474-row DB and was never committed to the live registry (477 of 489 live capability rows have `provenance IS NULL`). The 07-10 plan's Task 1 (`search_clis` matches capability vocabulary) also shipped. This plan closes two writer gaps the live corpus exposes, stops `populate()` from reverting the result, re-runs the dry run, parks the commit on an escalated DECISIONS entry, and after the operator resolves it, commits and measures the design's done-when.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), stdlib `sqlite3` in `tools/`, SQLModel in `core/`, pytest, the governance router at `http://localhost:9111/v1/chat/completions` (model `deepseek-v4-flash`; probed 2026-10-18, HTTP 200), governance CLIs `bin/foundations` and `bin/decisions` from `~/projects/00_Governance`.

**Spec:** `~/projects/20_CONSIGLIERE/docs/superpowers/specs/2026-10-18-capability-consolidation-design.md`, section 8 phase 0 row and section 9 ("Backfill's first live write is operator-gated on the dry-run report, later writes unattended"). Prior plans executed here: `docs/superpowers/plans/2026-07-03-capability-backfill.md` (Task 7), `docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md` (Task 2).

## Hierarchy

The design file is marked `spec-hierarchy: exempt`; this plan carries the phase's story. US-CLIREG-CAPMAP-01, under Epic "capability map", Solution "one discovery pipeline", Capability "the stack can say what it can do".

- AC-01: `FOUNDATIONS.md` exists in this repo with the single line the design dictates and `bin/foundations open` reports it.
- AC-02: after commit, enabled CLIs whose description contains a space and no `Error` count ≥ 550 of 612.
- AC-03: after commit, every enabled CLI has a capability row.
- AC-04: after commit, `sanity_ok IS NOT NULL` on ≥ 90 % of enabled CLIs' capability rows.
- AC-05: no description or capability field of the live DB changes before the operator resolves the escalated DECISIONS entry.
- AC-06: a `populate()` run after the commit leaves backfilled descriptions and capability rows in place.

## Global Constraints

- All `tools/` modules read and write the DB with raw `sqlite3` and explicit column lists, never `select(Cli)` (07-03 plan constraint; the live `cli` table now has `not_standalone`, the fixture in `tests/test_backfill_capabilities.py` does not).
- CSV strings for `input_types` / `output_types` / `intent_tags`; `confidence` is `inferred` for every backfilled row; `side_effect` in `none/writes-fs/network/destructive/unknown`.
- Provenance guard: a capability row with `provenance = 'manual'` is never overwritten by the writer or by `populate()`. This plan extends the protected set for `populate()` only (Task 3).
- No bare `except Exception` in new code; the existing `except Exception: rollback; raise` blocks in `write_commit` and `_persist_sanity` stay as they are.
- Commits use explicit pathspecs: `git commit -m "..." -- <paths>` (the shared-index hook at `~/.config/git/hooks/pre-commit` gates bare commits). Trailer: `Co-Authored-By: Claude <model> <noreply@anthropic.com>` naming the running model.
- Test runner: `.venv/bin/python -m pytest`. Commit-path tests carry `@needs_router` and call the real router for calibration.
- Live DB: `~/.hermes/cli-registry.db` (`DEFAULT_DB` in `core/cli/main.py:34`). The service on :9113 reads it per request; no restart after a commit.
- Gates in `tools/backfill_capabilities.py` stay as shipped: `FALLBACK_CAP = 300`, `SANITY_FAILURE_THRESHOLD = 0.10`, calibration must pass, `--commit` refuses otherwise. Never bypass with a flag.
- Long router runs go to the background with a log file, never in a foreground tool call (612 rows, two to four router calls each; runtime unmeasured, expect more than an hour).
- The handover asks for `/model opus` before build work. Tasks 2 and 3 are build work.
- Session stamp: this work is stamped `a2a-cli-registry` (re-stamped from `20_CONSIGLIERE` on 2026-10-18 because every file this plan touches lives here).

## Review Focus

1. A CLI whose `cli.path` no longer exists on disk: `_read_source` returns `""`, the regenerator returns `unknown purpose (<slug>)`, the sanity judge should fail it, and Task 4 reports how many such rows there are instead of letting them count as prose.
2. A proposals file (Task 2 `--from-proposals`) naming a slug no longer in `cli`: the writer must not create an orphan capability row. Pinned in Task 2.
3. A disabled CLI (`enabled = 0`, 24 live rows): must get no router calls and no proposal. Pinned in Task 2.
4. Router output wrapped in a markdown fence (the handover's gotcha 8): `_extract_json` must still parse it. Pinned in Task 2.
5. `populate()` running after the commit (not scheduled on this host today; live `source_run_id` values are `reconstructed-from-db`, `post-commit-register`, `manual-specreg-*`): must not revert descriptions or capability rows. Pinned in Task 3. Not covered: `register_cli.py` re-registering an existing slug rewrites its description (`~/projects/00_Governance/scripts/register_cli.py:181`); carried to phase 1, not fixed here.

## Baseline (recorded at execution, Task 1 Step 3)

| Measure | 2026-10-18 pre-plan | At Task 1 | After Task 5 |
|---|---|---|---|
| `cli` rows / enabled | 636 / 612 | | |
| enabled with prose description (`LIKE '% %' AND NOT LIKE '%Error%'`) | 153 | | |
| enabled with path-shaped description (`LIKE '%/%' AND NOT LIKE '% %'`) | 355 | | |
| enabled with error-shaped description (`LIKE '%Error%' OR LIKE '%Traceback%'`) | 112 | | |
| `capability` rows / `provenance IS NULL` / `manual` | 489 / 477 / 12 | | |
| enabled CLIs with no capability row | 125 | | |
| `sanity_ok IS NOT NULL` | 0 | | |
| HEAD | `8654325` | | |

---

### Task 1: Foundation entry, story, baseline

**Files:**
- Create: `FOUNDATIONS.md`
- Modify: `BACKLOG.md` (one story under `## Critical Path`)
- Modify: this plan (Baseline table)

**Interfaces:**
- Consumes: `~/projects/00_Governance/bin/foundations` (exit 1 when any entry is not `implemented`, prints the open lines; states are `open < specced < planned < implemented`).
- Produces: the foundation line Task 5 flips to `implemented`.

- [ ] **Step 1: Create `FOUNDATIONS.md`**

Four comment lines in the style of `~/projects/20_CONSIGLIERE/FOUNDATIONS.md` (format pointer; one-sentence premise: "the registry answers what each CLI on this host can do, for planners and for discovery gap matching"; what counts as a foundation; status line `drafted by agent 2026-10-18 per 20_CONSIGLIERE DECISIONS Q89`), then exactly one entry:

```
- capability map with real can-do descriptions | open | docs/superpowers/plans/2026-07-03-capability-backfill.md
```

- [ ] **Step 2: Verify the gate sees it**

Run: `cd ~/projects/00_Governance && bin/foundations open ~/projects/a2a-cli-registry; echo "exit $?"`
Expected: the one line printed with state `open`, then `exit 1`.

- [ ] **Step 3: Record the baseline**

Run the eight queries behind the Baseline table against `~/.hermes/cli-registry.db` (predicates as written in the table, all scoped to `enabled = 1` where the row says "enabled") plus `git rev-parse --short HEAD`, and fill the "At Task 1" column of this file. A number that differs from the pre-plan column is fine; a `cli` row count below 600 or a `manual` count other than 12 is not: stop and report before continuing.

- [ ] **Step 4: Add the story to `BACKLOG.md`**

Under `## Critical Path`, one entry in the surrounding entries' bullet style: `US-CLIREG-CAPMAP-01 — capability map with real can-do descriptions — AC-01..AC-06 in docs/superpowers/plans/2026-10-18-capability-map-phase0.md — status: in progress (phase 0 of the 20_CONSIGLIERE capability-consolidation design)`.

- [ ] **Step 5: Commit**

```bash
git add FOUNDATIONS.md BACKLOG.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
git commit -m "docs: declare the capability-map foundation and phase 0 plan (US-CLIREG-CAPMAP-01)" -- FOUNDATIONS.md BACKLOG.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
```

---

### Task 2: Writer covers the live corpus

The shipped writer only `UPDATE`s capability rows, so the 125 enabled CLIs without one get nothing (AC-03 fails), their sanity verdict has nowhere to land (AC-04 undercounts), and `--commit` re-runs the whole pipeline, so what the operator reviewed is not what gets written. Disabled rows also get router calls.

**Files:**
- Modify: `tools/backfill_capabilities.py` (`_fetch_all_cli_rows`, `_persist_sanity`, `write_commit`, `main`)
- Test: `tests/test_backfill_capabilities.py`, `tests/test_sanity_check.py`

**Interfaces:**
- Consumes: `_patch_pipeline(monkeypatch, ...)` and the `drifted_db` fixture already in `tests/test_backfill_capabilities.py` (fixture rows are inserted with positional `INSERT INTO cli VALUES (...)`, 17 columns, `enabled` is column 13).
- Produces: `_ensure_capability_row(con, slug) -> bool` (inserts `('', '', '', 'unknown', 'inferred')` with `provenance NULL` when the slug exists in `cli` and has no capability row; returns whether it inserted; returns False without inserting when the slug is not in `cli`). `main(argv)` gains `--from-proposals PATH` (requires `--commit`; loads `PATH` and the sibling `sanity_report.jsonl` next to it, skips `run_pipeline`, still runs `_run_calibration()` and the fail-rate gate from the loaded report, then `backup_db` and `write_commit`). `_fetch_all_cli_rows` returns only `enabled = 1` rows. Tasks 4 and 5 call these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backfill_capabilities.py`:

```python
def _insert_cli(con, slug, lang="python", enabled=1, description="30_x/orphan.py"):
    con.execute(
        "INSERT INTO cli VALUES (?,?,NULL,NULL,'/tmp/orphan.py','{}',?,NULL,NULL,'unknown',NULL,NULL,?,0,NULL,NULL,NULL)",
        (slug, lang, description, enabled),
    )


def test_pipeline_skips_disabled_rows(drifted_db, monkeypatch, tmp_path):
    con = sqlite3.connect(drifted_db); _insert_cli(con, "deadcli", enabled=0); con.commit(); con.close()
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = backfill.run_pipeline(drifted_db)
    assert "deadcli" not in {p["slug"] for p in result["proposals"]}
    assert result["summary"]["total_rows"] == 2


def test_persist_sanity_creates_placeholder_row_for_cli_without_capability(drifted_db):
    con = sqlite3.connect(drifted_db); _insert_cli(con, "orphan"); con.commit(); con.close()
    backfill.ensure_provenance_columns(drifted_db)
    backfill._persist_sanity(drifted_db, [{"slug": "orphan", "ok": True, "reason": "fine"}], 1.0)
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT sanity_ok, provenance, side_effect, confidence FROM capability WHERE cli_slug='orphan'").fetchone()
    con.close()
    assert row == (1, None, "unknown", "inferred")


def test_ensure_capability_row_refuses_unknown_slug(drifted_db):
    con = sqlite3.connect(drifted_db)
    assert backfill._ensure_capability_row(con, "never-registered") is False
    assert con.execute("SELECT count(*) FROM capability WHERE cli_slug='never-registered'").fetchone()[0] == 0
    con.close()


@needs_router
def test_commit_inserts_capability_row_when_missing(drifted_db, monkeypatch, tmp_path):
    con = sqlite3.connect(drifted_db); _insert_cli(con, "orphan"); con.commit(); con.close()
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.main(["--db", drifted_db, "--commit"])
    con = sqlite3.connect(drifted_db)
    cap = con.execute("SELECT input_types, provenance, description_provenance FROM capability WHERE cli_slug='orphan'").fetchone()
    desc = con.execute("SELECT description FROM cli WHERE slug='orphan'").fetchone()[0]
    con.close()
    assert cap == ("path", "static", "llm")
    assert desc == "A test CLI that converts things."


@needs_router
def test_commit_from_proposals_writes_reviewed_file_without_rerunning_pipeline(drifted_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    def _boom(db): raise AssertionError("pipeline must not run")
    monkeypatch.setattr(backfill, "run_pipeline", _boom)
    (tmp_path / "backfill_proposals.jsonl").write_text(json.dumps({
        "slug": "csv2json", "description": "Reviewed description.",
        "capability": {"input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"],
                       "side_effect": "none", "confidence": "inferred", "provenance": "static"},
    }) + "\n")
    (tmp_path / "sanity_report.jsonl").write_text(json.dumps({"slug": "csv2json", "ok": True, "reason": ""}) + "\n")
    backfill.main(["--db", drifted_db, "--commit", "--from-proposals", str(tmp_path / "backfill_proposals.jsonl")])
    con = sqlite3.connect(drifted_db)
    assert con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()[0] == "Reviewed description."
    con.close()


def test_from_proposals_requires_commit(drifted_db, tmp_path):
    with pytest.raises(SystemExit):
        backfill.main(["--db", drifted_db, "--from-proposals", str(tmp_path / "x.jsonl")])


@needs_router
def test_commit_from_proposals_ignores_slug_not_in_cli(drifted_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "backfill_proposals.jsonl").write_text(json.dumps({
        "slug": "ghost", "description": "Gone.",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "none",
                       "confidence": "inferred", "provenance": "llm"},
    }) + "\n")
    (tmp_path / "sanity_report.jsonl").write_text(json.dumps({"slug": "ghost", "ok": True, "reason": ""}) + "\n")
    backfill.main(["--db", drifted_db, "--commit", "--from-proposals", str(tmp_path / "backfill_proposals.jsonl")])
    con = sqlite3.connect(drifted_db)
    assert con.execute("SELECT count(*) FROM capability WHERE cli_slug='ghost'").fetchone()[0] == 0
    con.close()
```

Append to `tests/test_sanity_check.py`:

```python
def test_extract_json_strips_markdown_fence():
    assert sanity._extract_json('```json\n{"ok": true, "reason": "r"}\n```') == {"ok": True, "reason": "r"}
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backfill_capabilities.py tests/test_sanity_check.py -v -k "disabled or placeholder or unknown_slug or inserts_capability or from_proposals or fence"`
Expected: `test_extract_json_strips_markdown_fence` PASSES already (`_extract_json` slices from the first `{`; the test pins it). The others FAIL: `AttributeError: _ensure_capability_row`, `total_rows == 3`, `row is None`, and argparse rejecting `--from-proposals`.

- [ ] **Step 3: Implement in `tools/backfill_capabilities.py`**

`_fetch_all_cli_rows`: add `WHERE enabled = 1`.

`_ensure_capability_row(con, slug: str) -> bool`: `SELECT 1 FROM cli WHERE slug=?`, return False if absent; `SELECT 1 FROM capability WHERE cli_slug=?`, return False if present; else `INSERT INTO capability (cli_slug, intent_tags, input_types, output_types, side_effect, confidence) VALUES (?, '', '', '', 'unknown', 'inferred')` and return True. Call it at the top of the per-row loop in `_persist_sanity` and in `write_commit`; in both, `continue` when the slug has no `cli` row.

`_load_reviewed(path: Path) -> tuple[list[dict], list[dict]]`: reads `path` and `path.parent / "sanity_report.jsonl"` as JSON lines.

`main`: add `parser.add_argument("--from-proposals", type=Path, default=None)`. If set without `--commit`, `parser.error("--from-proposals requires --commit")`. If set, build `result = {"proposals", "sanity_results", "summary"}` with `calibration_ok` / `calibration_detail` from `_run_calibration()` and `sanity_fail_rate` from the loaded report, then fall through to the existing two REFUSED gates, `backup_db`, `write_commit`.

- [ ] **Step 4: Run the file's tests, then the full suite**

Run: `.venv/bin/python -m pytest tests/test_backfill_capabilities.py tests/test_sanity_check.py -v`
Expected: all PASS, including `test_all_474_rows_get_description_only_python_rows_get_capability` (its fixture rows are `enabled = 1`).

Run: `.venv/bin/python -m pytest -q`
Expected: 602 collected pre-plan plus the 8 new tests, all PASS. If `tests/test_server_overview.py` or `tests/test_web_overview_view.py` fail, read them: `/overview` counts capability rows and placeholder rows change those counts.

- [ ] **Step 5: Commit**

```bash
git add tools/backfill_capabilities.py tests/test_backfill_capabilities.py tests/test_sanity_check.py
git commit -m "feat(backfill): insert capability rows for CLIs without one, skip disabled rows, commit from a reviewed proposals file" -- tools/backfill_capabilities.py tests/test_backfill_capabilities.py tests/test_sanity_check.py
```

---

### Task 3: `populate()` keeps backfilled fields

Deviation from the design's "no design change; the plan is the design" (section 5): `core/populate.py:46` sets `cli.description` from the feed, and lines 66 to 76 delete and recreate the capability row unless `provenance == 'manual'`. One populate after Task 5 would undo it. Logged as a DECISIONS entry (Step 5), outcome `assumed`; the operator can strike this task.

**Files:**
- Modify: `core/models.py` (`Capability` gains `description_provenance: Optional[str] = None`, mirroring `provenance`, which commit `d022b46` added for the same reason)
- Modify: `core/populate.py:46`, `core/populate.py:66`
- Test: `tests/test_populate.py`

**Interfaces:**
- Consumes: `populate(session, source, adapters, vocab, clock)`, `FakeSource`, `_rec` from `tests/test_populate.py`; fixtures `db`, `clock` from `tests/conftest.py` (schema from `SQLModel.metadata.create_all`, so the new model field appears automatically).
- Produces: module constant `PRESERVED_PROVENANCE = ("manual", "static", "llm")` in `core/populate.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_populate.py`:

```python
def _seed_cli(db, description):
    db.add(Cli(slug="tool", lang="python", description=description))


def test_populate_preserves_backfilled_capability_row(db, clock):
    _seed_cli(db, "old")
    db.add(Capability(cli_slug="tool", intent_tags="export", input_types="path", output_types="json",
                      side_effect="none", confidence="inferred", provenance="llm"))
    db.commit()
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    populate(db, FakeSource([_rec("tool", ["text"], ["text"])]), [PythonAdapter()], vocab, clock)
    caps = db.exec(select(Capability).where(Capability.cli_slug == "tool")).all()
    assert [(c.provenance, c.intent_tags, c.input_types) for c in caps] == [("llm", "export", "path")]


def test_populate_keeps_description_when_backfilled(db, clock):
    _seed_cli(db, "Exports things to JSON.")
    db.add(Capability(cli_slug="tool", intent_tags="", input_types="", output_types="",
                      side_effect="unknown", confidence="inferred", description_provenance="llm"))
    db.commit()
    rec = _rec("tool", ["text"], ["text"]); rec.description = "scripts/tool.py"
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)
    assert db.get(Cli, "tool").description == "Exports things to JSON."


def test_populate_still_overwrites_feed_owned_rows(db, clock):
    _seed_cli(db, "old")
    db.add(Capability(cli_slug="tool", intent_tags="x", input_types="x", output_types="x",
                      side_effect="none", confidence="inferred"))
    db.commit()
    rec = _rec("tool", ["text"], ["text"]); rec.description = "scripts/tool.py"
    vocab = VocabularyRegistry(registered={"text"}, aliases={})
    populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)
    assert db.get(Cli, "tool").description == "scripts/tool.py"
    assert db.exec(select(Capability).where(Capability.cli_slug == "tool")).one().intent_tags == "convert"
```

`Cli(slug=, lang=, description=)` is the constructor shape `tests/test_catalog.py` already uses; the other columns have model defaults.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_populate.py -v -k "backfilled or feed_owned"`
Expected: the first two FAIL (`TypeError` on `description_provenance`, then provenance `None` / description overwritten once the model has the field); the third PASSES already and guards the existing behaviour.

- [ ] **Step 3: Implement**

`core/models.py`: add `description_provenance: Optional[str] = None` after `provenance`, with a two-line comment saying the backfill owns descriptions marked `llm`.

`core/populate.py`: define `PRESERVED_PROVENANCE = ("manual", "static", "llm")`. Move the `old_caps` query above the field assignments. Assign `cli.description = rec.description` only when no `old_caps` row has `description_provenance == "llm"`. Replace `if not any(c.provenance == "manual" ...)` with `if not any(c.provenance in PRESERVED_PROVENANCE ...)`. Update the comment above it to name the backfill as the second owner.

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m pytest tests/test_populate.py tests/test_e2e.py tests/test_cli.py tests/test_plan_health.py tests/test_planner_probe.py -v`, then `.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Log the deviation and commit**

```bash
cd ~/projects/00_Governance && bin/decisions add a2a-cli-registry --context US-CLIREG-CAPMAP-01 --category deviation \
  --question "populate() reverts backfilled descriptions and capability rows on its next run; change populate although the design says the 07-03 plan is the design?" \
  --options "extend populate's preserved provenance set to static/llm and keep llm descriptions / leave populate alone and re-run the backfill after every populate / accept the risk" \
  --chosen "extend populate" --decided-by agent --outcome assumed \
  --justification "populate is not scheduled on this host today but one run would undo 612 descriptions; the feed's inference is what produced the path-shaped descriptions, so it is the weaker source for these rows. Trade-off: feed-side capability inference never refreshes a backfilled slug." \
  --ref "core/populate.py, tests/test_populate.py, design section 5" --apply
cd ~/projects/a2a-cli-registry
git add core/models.py core/populate.py tests/test_populate.py DECISIONS.md
git commit -m "fix(populate): preserve backfilled (static/llm) capability rows and llm descriptions" -- core/models.py core/populate.py tests/test_populate.py DECISIONS.md
```

---

### Task 4: Dry run against the live registry, report, escalate

This is Task 7 Steps 1 to 4 of the 07-03 plan, re-run on today's corpus. The dry run writes `sanity_ok` / `sanity_reason` / `sanity_checked_at` to the live DB (shipped behaviour since `d42a30b`) and, after Task 2, placeholder capability rows for CLIs without one. It writes no description and no capability field. It overwrites the two tracked jsonl files in the repo root.

**Files:**
- Modify: `backfill_proposals.jsonl`, `sanity_report.jsonl` (regenerated), `DECISIONS.md` (escalated entry), this plan (run summary pasted under Step 4)

**Interfaces:**
- Consumes: `tools.backfill_capabilities.main(["--db", DEFAULT_DB])`.
- Produces: the two jsonl files and the DECISIONS question number Task 5 waits on.

- [ ] **Step 1: Confirm the router answers**

Run:
```bash
curl -s -m 25 -X POST http://localhost:9111/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer router-local" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"Reply with the JSON {\"ok\":true} only."}],"max_tokens":20,"temperature":0}' -w "\nhttp %{http_code}\n"
```
Expected: `choices[0].message.content` of `{"ok":true}` and `http 200`. Anything else: stop; the run would mark every row unreachable and persist nothing useful.

- [ ] **Step 2: Start the dry run in the background**

```bash
mkdir -p ~/.local/state/a2a-cli-registry
cd ~/projects/a2a-cli-registry && nohup .venv/bin/python -m tools.backfill_capabilities --db ~/.hermes/cli-registry.db \
  > ~/.local/state/a2a-cli-registry/backfill-dryrun-$(date +%Y%m%d-%H%M).log 2>&1 &
echo $!
```
Then wait with a Monitor on the log for the line `"elapsed_seconds"` (the summary JSON is the last thing printed). Do not poll in a foreground loop. Runtime is unmeasured; the July run's elapsed was not recorded.

- [ ] **Step 3: Read the summary and the gates**

Run: `tail -14 ~/.local/state/a2a-cli-registry/backfill-dryrun-*.log`
Expected: JSON with `total_rows` = enabled count (612 unless Task 1's baseline differed), `fallback_count ≤ 300`, `calibration_ok: true`, `sanity_fail_rate ≤ 0.10`. A `STOP:` line or any `unreachable` text in `calibration_detail` means a gate failed: do not tune the thresholds; follow Task 7 Step 3 of the 07-03 plan (fix the extractor, regenerator or checker, re-run unit tests, re-run this step) and record the reason in the DECISIONS entry below.

- [ ] **Step 4: Measure the proposals against AC-02 and Review Focus item 1**

```bash
cd ~/projects/a2a-cli-registry && .venv/bin/python - <<'EOF'
import json
P = [json.loads(l) for l in open("backfill_proposals.jsonl")]
S = {r["slug"]: r for r in (json.loads(l) for l in open("sanity_report.jsonl"))}
prose = sum(1 for p in P if " " in p["description"] and "Error" not in p["description"])
unknown = [p["slug"] for p in P if p["description"].startswith("unknown purpose")]
fails = [s for s, r in S.items() if not r["ok"]]
print(f"rows={len(P)} prose={prose} unknown_purpose={len(unknown)} sanity_fail={len(fails)}")
print("unknown sample:", unknown[:10]); print("fail sample:", fails[:10])
EOF
```
Expected: `prose ≥ 550`. Below that, AC-02 cannot be met by committing; report the shortfall in the DECISIONS entry with the `unknown_purpose` list (those are CLIs whose source path is gone, a registry-hygiene finding for phase 1, not a tuning target). Paste the summary JSON and this output into this plan file under this step.

- [ ] **Step 5: File the escalated decision and commit the artifacts**

```bash
cd ~/projects/00_Governance && bin/decisions add a2a-cli-registry --context US-CLIREG-CAPMAP-01 --category gate-resolution \
  --question "Commit the reviewed backfill proposals to ~/.hermes/cli-registry.db? Dry run <date>: rows=<n> prose=<n>/612 fallback=<n> sanity_fail_rate=<x> calibration_ok=<bool> unknown_purpose=<n>" \
  --options "commit from the reviewed file / tune and re-run / stop phase 0" --outcome escalated --decided-by human \
  --justification "First live write of LLM-generated descriptions into the registry; design section 9 gates it on this report. Review: backfill_proposals.jsonl (head -40), sanity_report.jsonl ok:false rows, log at ~/.local/state/a2a-cli-registry/backfill-dryrun-<stamp>.log. Later runs write unattended through the sanity gate." \
  --ref "docs/superpowers/plans/2026-10-18-capability-map-phase0.md Task 4" --apply
cd ~/projects/a2a-cli-registry
git add backfill_proposals.jsonl sanity_report.jsonl DECISIONS.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
git commit -m "chore(backfill): dry-run proposals and sanity report against the live registry; commit escalated to operator" -- backfill_proposals.jsonl sanity_report.jsonl DECISIONS.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
```

**STOP after this step.** Task 5 starts only when `bin/decisions open -p a2a-cli-registry` no longer lists this question. The operator resolves it with:

```bash
cd ~/projects/00_Governance && bin/decisions resolve a2a-cli-registry <n> --chosen "commit from the reviewed file" --decided-by human --apply
```

---

### Task 5: Commit to the live registry, measure, close the foundation

**Files:**
- Modify: `FOUNDATIONS.md` (state `open` to `implemented`), `BACKLOG.md` (story status), `docs/superpowers/plans/2026-07-03-capability-backfill.md` and `docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md` (one status line each under the title), this plan (Baseline "After Task 5" column)

**Interfaces:**
- Consumes: Task 2's `--from-proposals`; Task 4's committed `backfill_proposals.jsonl` at the HEAD the operator reviewed.

- [ ] **Step 1: Confirm the gate is open and the file is the reviewed one**

Run: `cd ~/projects/00_Governance && bin/decisions open -p a2a-cli-registry | grep -c "Commit the reviewed backfill"` → `0`.
Run: `cd ~/projects/a2a-cli-registry && git status --porcelain backfill_proposals.jsonl sanity_report.jsonl` → empty (unchanged since Task 4's commit).

- [ ] **Step 2: Commit from the reviewed file**

```bash
cd ~/projects/a2a-cli-registry && .venv/bin/python -m tools.backfill_capabilities --db ~/.hermes/cli-registry.db --commit --from-proposals backfill_proposals.jsonl 2>&1 | tail -5
ls -la ~/.hermes/cli-registry.db.bak-$(git rev-parse --short HEAD)
```
Expected: no `REFUSED` line; the backup file exists with the current short SHA. The calibration step makes eight router calls; the regeneration does not re-run.

- [ ] **Step 3: Acceptance queries (AC-02, AC-03, AC-04)**

```bash
sqlite3 ~/.hermes/cli-registry.db "
SELECT count(*) FROM cli WHERE enabled=1 AND description LIKE '% %' AND description NOT LIKE '%Error%';
SELECT count(*) FROM cli WHERE enabled=1 AND slug NOT IN (SELECT cli_slug FROM capability);
SELECT count(*) FROM capability c JOIN cli ON cli.slug=c.cli_slug WHERE cli.enabled=1 AND c.sanity_ok IS NOT NULL;
SELECT provenance, count(*) FROM capability GROUP BY 1;" | tr '\n' ' '
```
Expected: first ≥ 550, second 0, third ≥ 551 (90 % of 612), `manual` still 12. Fill the "After Task 5" column of the Baseline table from these plus the other predicates.

- [ ] **Step 4: Live search probe (07-10 plan Task 2)**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/a2a-cli-registry overview --query file:pdf --db ~/.hermes/cli-registry.db 2>&1 | grep -ci "generate.pdf"`
Expected: ≥ 1. Record the count under this step. If `overview` renders a page instead of listing rows, call `core.catalog.queries.search_clis(session, "file:pdf")` directly against a `sqlite:///` engine on the live DB and record the slugs.

- [ ] **Step 5: Bookkeeping**

`FOUNDATIONS.md`: change `| open |` to `| implemented |` on the one line. Run `cd ~/projects/00_Governance && bin/foundations open ~/projects/a2a-cli-registry; echo "exit $?"` → nothing open, `exit 0`.

`BACKLOG.md`: story status `in progress` to `done 2026-10-<dd> (phase 0; phases 1 to 4 in 20_CONSIGLIERE)`.

Under the H1 of `docs/superpowers/plans/2026-07-03-capability-backfill.md`, add: `**Status 2026-10-<dd>:** Tasks 1 to 6 shipped 2026-07 (commits e5c0129 to c825cf1); Task 7 executed against the live registry by docs/superpowers/plans/2026-10-18-capability-map-phase0.md Tasks 4 and 5. Checkboxes below were never ticked and are left as written.` Same shape under the H1 of the 07-10 plan: Task 1 shipped (`git log --oneline -1 -- core/catalog/queries.py` for the SHA), Task 2 executed as Task 5 Step 4 here.

- [ ] **Step 6: Commit and push**

```bash
git add FOUNDATIONS.md BACKLOG.md docs/superpowers/plans/2026-07-03-capability-backfill.md docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
git commit -m "docs: capability map foundation implemented; phase 0 acceptance recorded (US-CLIREG-CAPMAP-01)" -- FOUNDATIONS.md BACKLOG.md docs/superpowers/plans/2026-07-03-capability-backfill.md docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
git push
```

Then in 20_CONSIGLIERE: the design's section 8 phase 0 row is done; phase 1 (feeds) gets its own `superpowers:writing-plans` run. Carry forward to that plan: `register_cli.py:181` rewrites descriptions on re-register (Review Focus item 5), and the `unknown_purpose` slugs from Task 4 Step 4 are registry rows whose source files are gone.

---

## Self-review notes

Spec coverage: the section 8 phase 0 row (two prior plans executed, dry run first, operator gate, re-baseline) is Tasks 1, 4 and 5; the done-when triple is AC-02 to AC-04, measured in Task 5 Step 3; the FOUNDATIONS line is Task 1 and is flipped in Task 5; section 9's "later writes unattended" is the `--from-proposals` path plus the shipped sanity gate. Task 3 is the one deviation and is logged as such. Not in this plan: feeds, lifts, gap matcher, retirements (phases 1 to 4).

Type consistency: `_ensure_capability_row(con, slug) -> bool` is named identically in Task 2's interface, tests and implementation; `PRESERVED_PROVENANCE` and `description_provenance` match between Task 3's tests and code; `--from-proposals` takes the proposals path and infers the report path from it in both the interface and Task 5 Step 2.

Proportion: two small code changes and one operator-gated procedure; the only code blocks are tests and shell commands.
