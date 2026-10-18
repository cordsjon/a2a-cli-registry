# Capability Map Phase 0 Implementation Plan

**Status 2026-10-18 19:30 (operator ruling, 20_CONSIGLIERE DECISIONS Q92): NOT cleared for execution.** This plan was written before the operator ruled "spec → architecture review → LLM panel → plans" for the capability-consolidation design. It goes through `sh:architecture-panel`, then `sh:spec-panel`, then a Codex review, and only then to execution. Do not start Task 1 until all three are recorded here with their verdicts. Pre-panel grounding review (Codex + DeepSeek) ran 2026-10-18 20:26; findings and the per-item triage are at the bottom of this file, and the edits they produced are folded into the tasks above.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every enabled CLI in the live registry a prose "can do" description and a sanity-checked capability row, by executing the already-built backfill pipeline against `~/.hermes/cli-registry.db` behind the operator gate the design names.

**Architecture:** The pipeline exists. Tasks 1 to 6 of `docs/superpowers/plans/2026-07-03-capability-backfill.md` shipped in July (commits `e5c0129` through `c825cf1`: `tools/description_regenerator.py`, `tools/capability_extractor.py`, `tools/capability_llm_fallback.py`, `tools/sanity_check.py`, `tools/capability_repair.py`, `tools/backfill_capabilities.py`; 96 tests green on 2026-10-18). Its Task 7 dry run ran once against a 474-row DB and was never committed to the live registry (477 of 489 live capability rows have `provenance IS NULL`). The 07-10 plan's Task 1 (`search_clis` matches capability vocabulary) also shipped. This plan closes two writer gaps the live corpus exposes, stops `populate()` from reverting the result, re-runs the dry run, parks the commit on an escalated DECISIONS entry, and after the operator resolves it, commits and measures the design's done-when.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), stdlib `sqlite3` in `tools/`, SQLModel in `core/`, pytest, the governance router at `http://localhost:9111/v1/chat/completions` (model `deepseek-v4-flash`; probed 2026-10-18, HTTP 200), governance CLIs `bin/foundations` and `bin/decisions` from `~/projects/00_Governance`.

**Spec:** `~/projects/20_CONSIGLIERE/docs/superpowers/specs/2026-10-18-capability-consolidation-design.md`, section 8 phase 0 row and section 9 ("Backfill's first live write is operator-gated on the dry-run report, later writes unattended"). Prior plans executed here: `docs/superpowers/plans/2026-07-03-capability-backfill.md` (Task 7), `docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md` (Task 2).

## Hierarchy

The design file is marked `spec-hierarchy: exempt`; this plan carries the phase's story. US-CLIREG-CAPMAP-01, under Epic "capability map", Solution "one discovery pipeline", Capability "the stack can say what it can do".

- AC-01: `FOUNDATIONS.md` exists in this repo with the single line the design dictates and `bin/foundations open` reports it.
- AC-02: after commit, enabled CLIs whose description contains a space, no `Error`, and is not the regenerator's `unknown purpose (<slug>)` sentinel count ≥ 550 of 612.
- AC-03: after commit, every enabled CLI has a capability row.
- AC-04: after commit, `sanity_ok IS NOT NULL` on ≥ 90 % of enabled CLIs' capability rows.
- AC-05: no field of the live DB's `cli` or `capability` tables changes before the operator resolves the escalated DECISIONS entry (the dry run targets a snapshot copy, Task 4).
- AC-06: a `populate()` run after the commit leaves backfilled descriptions and capability rows in place.

## Global Constraints

- All `tools/` modules read and write the DB with raw `sqlite3` and explicit column lists, never `select(Cli)` (07-03 plan constraint; the live `cli` table now has `not_standalone`, the fixture in `tests/test_backfill_capabilities.py` does not).
- CSV strings for `input_types` / `output_types` / `intent_tags`; `confidence` is `inferred` for every backfilled row; `side_effect` in `none/writes-fs/network/destructive/unknown`.
- Provenance guard: a capability row with `provenance = 'manual'` is never overwritten by the writer or by `populate()`. This plan extends the protected set for `populate()` only (Task 3).
- Provenance vocabulary (shipped, `write_commit` in `tools/backfill_capabilities.py`): `capability.provenance` and `capability.description_provenance` are each `NULL` (feed-owned, never backfilled), `static` (extractor), `llm` (router fallback; every backfilled description is marked `llm`) or `manual` (operator). The writer overwrites `NULL` / `static` / `llm` and never `manual`.
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
- capability map with real can-do descriptions | open | docs/superpowers/plans/2026-10-18-capability-map-phase0.md
```

- [ ] **Step 2: Verify the gate sees it**

Run: `cd ~/projects/00_Governance && bin/foundations open ~/projects/a2a-cli-registry; echo "exit $?"`
Expected: the one line printed with state `open`, then `exit 1`.

- [ ] **Step 3: Record the baseline**

Run the eight queries behind the Baseline table against `~/.hermes/cli-registry.db` (predicates as written in the table, all scoped to `enabled = 1` where the row says "enabled") plus `git rev-parse --short HEAD`, and fill the "At Task 1" column of this file. A number that differs from the pre-plan column is fine; a `cli` row count below 600 (636 pre-plan; losing 36 rows means a registry sweep ran, not drift) or a `manual` count other than 12 (an operator hand-edit landed after the plan was written and the operator should know before the writer runs) is not: stop and report before continuing.

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
- Produces: `_ensure_capability_row(con, slug) -> bool` (inserts `('', '', '', 'unknown', 'inferred')` with `provenance NULL` when the slug exists in `cli` and has no capability row; returns whether it inserted; returns False without inserting when the slug is not in `cli`). Callers treat the two False cases differently: slug not in `cli` → `continue` (no orphan row); slug in `cli` → fall through to the existing `UPDATE`, which the shipped guard (`provenance in (None, 'static', 'llm')`) lets through for the fresh placeholder, so the placeholder ends up carrying the proposal's `provenance` and `description_provenance = 'llm'`. `_load_reviewed(path) -> tuple[list[dict], list[dict]]` reads `PATH` and the sibling `sanity_report.jsonl` and refuses (`REFUSED: reviewed report does not cover the proposals (<detail>)` to stderr, exit 1) unless the report holds exactly one verdict per proposal slug and none for any other slug. `main(argv)` gains `--from-proposals PATH` (requires `--commit`; skips `run_pipeline`; `sanity_fail_rate = fails / len(report)` over the validated report; runs `_run_calibration()` and the two shipped REFUSED gates; then `backup_db`, `_persist_sanity(db, report, now)`, `write_commit`, in that order, so the first live write of any kind sits behind the backup). `_fetch_all_cli_rows` returns only `enabled = 1` rows. Tasks 4 and 5 call these.

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
    assert con.execute("SELECT sanity_ok FROM capability WHERE cli_slug='csv2json'").fetchone()[0] == 1
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


def test_commit_from_proposals_refuses_report_missing_a_verdict(drifted_db, tmp_path, capsys):
    (tmp_path / "backfill_proposals.jsonl").write_text(json.dumps({
        "slug": "csv2json", "description": "Reviewed description.",
        "capability": {"input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"],
                       "side_effect": "none", "confidence": "inferred", "provenance": "static"},
    }) + "\n")
    (tmp_path / "sanity_report.jsonl").write_text(json.dumps({"slug": "other", "ok": True, "reason": ""}) + "\n")
    with pytest.raises(SystemExit):
        backfill.main(["--db", drifted_db, "--commit", "--from-proposals", str(tmp_path / "backfill_proposals.jsonl")])
    assert "REFUSED: reviewed report does not cover" in capsys.readouterr().err
    con = sqlite3.connect(drifted_db)
    assert con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()[0] != "Reviewed description."
    con.close()
```

The refusal test needs no router: `_load_reviewed` validates before `_run_calibration()` runs.

Append to `tests/test_sanity_check.py`:

```python
def test_extract_json_strips_markdown_fence():
    assert sanity._extract_json('```json\n{"ok": true, "reason": "r"}\n```') == {"ok": True, "reason": "r"}
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backfill_capabilities.py tests/test_sanity_check.py -v -k "disabled or placeholder or unknown_slug or inserts_capability or from_proposals or fence"`
Expected: `test_extract_json_strips_markdown_fence` PASSES already (`_extract_json` slices from the first `{`; the test pins it). The others FAIL: `AttributeError: _ensure_capability_row` (`unknown_slug`), `total_rows == 3` (`disabled`), `row is None` (`placeholder`), `cap is None` (`inserts_capability`: the shipped writer only updates), and argparse rejecting `--from-proposals` (the four `from_proposals` tests).

- [ ] **Step 3: Implement in `tools/backfill_capabilities.py`**

`_fetch_all_cli_rows`: add `WHERE enabled = 1`.

`_ensure_capability_row(con, slug: str) -> bool`: `SELECT 1 FROM cli WHERE slug=?`, return False if absent; `SELECT 1 FROM capability WHERE cli_slug=?`, return False if present; else `INSERT INTO capability (cli_slug, intent_tags, input_types, output_types, side_effect, confidence) VALUES (?, '', '', '', 'unknown', 'inferred')` and return True. Call it at the top of the per-row loop in `_persist_sanity` and in `write_commit`; in both, `continue` when the slug has no `cli` row.

`_load_reviewed(path: Path) -> tuple[list[dict], list[dict]]`: reads `path` and `path.parent / "sanity_report.jsonl"` as JSON lines; builds `verdicts = {r["slug"]: r}` and refuses (`REFUSED: reviewed report does not cover the proposals (<detail>)` to stderr, `sys.exit(1)`) when a report slug repeats, a proposal slug has no verdict, or a verdict names a slug absent from the proposals.

`main`: add `parser.add_argument("--from-proposals", type=Path, default=None)`. If set without `--commit`, `parser.error("--from-proposals requires --commit")`. If set, build `result = {"proposals", "sanity_results", "summary"}` with `calibration_ok` / `calibration_detail` from `_run_calibration()` and `sanity_fail_rate = fails / len(report)` from the validated report, then fall through to the existing two REFUSED gates, `backup_db`, then `_persist_sanity(args.db, report, time.time())` (the replay is the only path that writes sanity verdicts to the live DB, since Task 4's dry run targets a snapshot), then `write_commit`.

- [ ] **Step 4: Run the file's tests, then the full suite**

Run: `.venv/bin/python -m pytest tests/test_backfill_capabilities.py tests/test_sanity_check.py -v`
Expected: all PASS, including `test_all_474_rows_get_description_only_python_rows_get_capability` (its fixture rows are `enabled = 1`).

Run: `.venv/bin/python -m pytest -q`
Expected: 602 collected pre-plan plus the 9 new tests, all PASS. If `tests/test_server_overview.py` or `tests/test_web_overview_view.py` fail, read them: `/overview` counts capability rows and placeholder rows change those counts.

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
    populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)  # second run: the marker must survive the row recreation
    assert db.get(Cli, "tool").description == "Exports things to JSON."
    assert db.exec(select(Capability).where(Capability.cli_slug == "tool")).one().description_provenance == "llm"


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
Expected: the first FAILS on the provenance assertion (the feed recreated the row, so it comes back with provenance `None` and `intent_tags` `convert`); the second FAILS with `TypeError` on `description_provenance` and, once the model has the field, on the overwritten description; the third PASSES already and guards the existing behaviour.

- [ ] **Step 3: Implement**

`core/models.py`: add `description_provenance: Optional[str] = None` after `provenance`, with a two-line comment saying the backfill owns descriptions marked `llm`.

`core/populate.py`: define `PRESERVED_PROVENANCE = ("manual", "static", "llm")`. Move the `old_caps` query above the field assignments. Assign `cli.description = rec.description` only when no `old_caps` row has `description_provenance == "llm"`. Replace `if not any(c.provenance == "manual" ...)` with `if not any(c.provenance in PRESERVED_PROVENANCE ...)`. When the row IS recreated (feed-owned capability, e.g. a shell CLI whose only backfilled field is its description, so `provenance` is `NULL` and `description_provenance` is `llm`), pass `description_provenance=` the old row's value into the new `Capability(...)`: without that the marker dies with the deleted row and the second `populate()` overwrites the description (AC-06). Update the comment above it to name the backfill as the second owner.

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

This is Task 7 Steps 1 to 4 of the 07-03 plan, re-run on today's corpus. The dry run writes `sanity_ok` / `sanity_reason` / `sanity_checked_at` (shipped behaviour since `d42a30b`) and, after Task 2, placeholder capability rows for CLIs without one, so it runs against a **snapshot copy** of the registry, never the live file: AC-05 holds until the operator resolves the gate, and the live DB's first write of any kind is Task 5's, behind `backup_db`. The sanity verdicts reach the live DB through the replay path (Task 2). The run overwrites the two tracked jsonl files in the repo root.

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
STAMP=$(date +%Y%m%d-%H%M); SNAP=~/.local/state/a2a-cli-registry/registry-snapshot-$STAMP.db
sqlite3 ~/.hermes/cli-registry.db ".backup '$SNAP'"
cd ~/projects/a2a-cli-registry && nohup .venv/bin/python -m tools.backfill_capabilities --db "$SNAP" \
  > ~/.local/state/a2a-cli-registry/backfill-dryrun-$STAMP.log 2>&1 &
echo "$! $SNAP"
```
`.backup` is a consistent copy while the :9113 service keeps reading the live file. Every write the run makes (sanity fields, placeholder rows, the provenance columns) lands in the snapshot.
Then wait with a Monitor on the log for the line `"elapsed_seconds"` (the summary JSON is the last thing printed). Do not poll in a foreground loop. Runtime is unmeasured; the July run's elapsed was not recorded.

- [ ] **Step 3: Read the summary and the gates**

Run: `tail -11 ~/.local/state/a2a-cli-registry/backfill-dryrun-$STAMP.log` (the summary is the 11-line indented JSON `run_pipeline` prints last: nine keys plus braces)
Expected: JSON with `total_rows` = enabled count (612 unless Task 1's baseline differed), `fallback_count ≤ 300`, `calibration_ok: true`, `sanity_fail_rate ≤ 0.10`. A `STOP:` line or any `unreachable` text in `calibration_detail` means a gate failed: do not tune the thresholds; follow Task 7 Step 3 of the 07-03 plan (fix the extractor, regenerator or checker, re-run unit tests, re-run this step) and record the reason in the DECISIONS entry below.

- [ ] **Step 4: Measure the proposals against AC-02 and Review Focus item 1**

```bash
cd ~/projects/a2a-cli-registry && .venv/bin/python - <<'EOF'
import json
P = [json.loads(l) for l in open("backfill_proposals.jsonl")]
S = {r["slug"]: r for r in (json.loads(l) for l in open("sanity_report.jsonl"))}
import os, sqlite3
def is_prose(d): return " " in d and "Error" not in d and not d.startswith("unknown purpose")
unknown = [p["slug"] for p in P if p["description"].startswith("unknown purpose")]
prose = sum(1 for p in P if is_prose(p["description"]))
con = sqlite3.connect(os.path.expanduser("~/.hermes/cli-registry.db"))
try:
    manual_desc = {r[0] for r in con.execute("SELECT cli_slug FROM capability WHERE description_provenance='manual'")}
except sqlite3.OperationalError:  # live DB predates the column: nothing is manual yet
    manual_desc = set()
con.close()
prose_writable = sum(1 for p in P if is_prose(p["description"]) and p["slug"] not in manual_desc)
fails = [s for s, r in S.items() if not r["ok"]]
print(f"rows={len(P)} prose={prose} prose_writable={prose_writable} unknown_purpose={len(unknown)} manual_desc={len(manual_desc)} sanity_fail={len(fails)}")
print("unknown sample:", unknown[:10]); print("fail sample:", fails[:10])
EOF
shasum -a 256 backfill_proposals.jsonl sanity_report.jsonl   # both hashes go into the DECISIONS question below; Task 5 Step 1 checks them
```
Expected: `prose_writable ≥ 550` (the writer skips `manual` descriptions, so this is the number that lands; `prose` is what the generator produced; neither counts the `unknown purpose` sentinel, AC-02 excludes it). Below that, AC-02 cannot be met by committing; report the shortfall in the DECISIONS entry with the `unknown_purpose` list (those are CLIs whose source path is gone, a registry-hygiene finding for phase 1, not a tuning target). Paste the summary JSON and this output into this plan file under this step.

- [ ] **Step 5: File the escalated decision and commit the artifacts**

```bash
cd ~/projects/00_Governance && bin/decisions add a2a-cli-registry --context US-CLIREG-CAPMAP-01 --category gate-resolution \
  --question "Commit the reviewed backfill proposals to ~/.hermes/cli-registry.db? Dry run <date> on snapshot <SNAP>: rows=<n> prose_writable=<n>/612 fallback=<n> sanity_fail_rate=<x> calibration_ok=<bool> unknown_purpose=<n>; sha256 backfill_proposals.jsonl=<h1> sanity_report.jsonl=<h2>" \
  --options "commit from the reviewed file / tune and re-run / stop phase 0" --outcome escalated --decided-by human \
  --justification "First live write of LLM-generated descriptions into the registry; design section 9 gates it on this report. Review: backfill_proposals.jsonl (head -40), sanity_report.jsonl ok:false rows, log at ~/.local/state/a2a-cli-registry/backfill-dryrun-<stamp>.log. Later runs write unattended through the sanity gate." \
  --ref "docs/superpowers/plans/2026-10-18-capability-map-phase0.md Task 4" --apply
cd ~/projects/a2a-cli-registry
git add backfill_proposals.jsonl sanity_report.jsonl DECISIONS.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
git commit -m "chore(backfill): dry-run proposals and sanity report against the live registry; commit escalated to operator" -- backfill_proposals.jsonl sanity_report.jsonl DECISIONS.md docs/superpowers/plans/2026-10-18-capability-map-phase0.md
```

**STOP after this step.** Task 5 starts only when the operator has resolved the question with the exact chosen text below; Task 5 Step 1 reads the superseding entry, not the open list, because "tune and re-run" and "stop phase 0" also close the question. The operator resolves it with:

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

`resolve` closes Q<n> by appending a superseding entry Q<m> (`**Supersedes:** Q<n> — resolved`); read that entry.
Run: `cd ~/projects/00_Governance && bin/decisions show -p a2a-cli-registry <m> | grep -cE '^\*\*(Chosen:\*\* commit from the reviewed file|Decided-by:\*\* human|Supersedes:\*\* Q<n> — resolved)$'` → `3`. Any other count, including a `show` error, blocks Task 5.
Run: `cd ~/projects/a2a-cli-registry && shasum -a 256 backfill_proposals.jsonl sanity_report.jsonl` → the two hashes recorded in Q<n>'s question. A later commit can replace either file and leave the tree clean, so the hashes, not `git status`, identify what the operator reviewed.

- [ ] **Step 2: Commit from the reviewed file**

```bash
cd ~/projects/a2a-cli-registry && SHA=$(git rev-parse --short HEAD)
.venv/bin/python -m tools.backfill_capabilities --db ~/.hermes/cli-registry.db --commit --from-proposals backfill_proposals.jsonl 2>&1 | tail -5
ls -la ~/.hermes/cli-registry.db.bak-$SHA
```
Expected: no `REFUSED` line; the backup file exists under the SHA captured before the run (captured first so a future `git commit` inserted in between cannot make the check pass against the wrong file). The calibration step makes eight router calls; the regeneration does not re-run; the reviewed sanity verdicts are persisted in this same run.

- [ ] **Step 3: Acceptance queries (AC-02, AC-03, AC-04)**

```bash
sqlite3 ~/.hermes/cli-registry.db "
SELECT count(*) FROM cli WHERE enabled=1 AND description LIKE '% %' AND description NOT LIKE '%Error%' AND description NOT LIKE 'unknown purpose%';
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

## Duo review — pre-panel round 1

_Generated by review-duo at 2026-10-18T18:27:30Z. Phase artifacts: `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/plans/2026-10-18-capability-map-phase0-duo-20261018-202600`_
_Two independent reviewers, shared context. Claude triages per-comment. No LLM-driven synthesis._

### DeepSeek findings

## Findings — DEEPSEEK

### [CRITICAL] Task 2 test asserts a `description_provenance` column that Task 3 introduces, but Task 2 ships first
- What: `test_commit_inserts_capability_row_when_missing` selects `description_provenance` from `capability` and asserts `cap == ("path", "static", "llm")`, but `description_provenance` is only added to the `Capability` model in Task 3 Step 3. Task 2's commit lands before Task 3's.
- Where: Task 2 Step 1, `test_commit_inserts_capability_row_when_missing` — `SELECT input_types, provenance, description_provenance FROM capability WHERE cli_slug='orphan'` and `assert cap == ("path", "static", "llm")`.
- Why it matters: The `drifted_db` fixture is built from `SQLModel.metadata.create_all` (per Task 3's Interfaces note), so at Task 2 time the `capability` table has no `description_provenance` column. The test will fail with `sqlite3.OperationalError: no such column` — and worse, the assertion `("path", "static", "llm")` also encodes a `provenance = "static"` value that the writer's `_ensure_capability_row` inserts as `provenance NULL` (per Task 2's own interface spec: "inserts `('', '', '', 'unknown', 'inferred')` with `provenance NULL`"). The test as written cannot pass under Task 2's implementation even ignoring the missing column.
- Suggested fix: Either (a) move the `description_provenance` model change into Task 2 (it's a schema addition, not a populate change), or (b) drop `description_provenance` from this test's SELECT and assert only `(input_types, provenance) == ("path", None)` — matching what `_ensure_capability_row` actually inserts. Also reconcile: the interface says `provenance NULL`, the test expects `"static"`.
- Confidence: high

### [CRITICAL] `_ensure_capability_row` inserts `provenance NULL`, but the test expects `"static"` — the writer's contract is self-contradictory
- What: Task 2's Interfaces block says `_ensure_capability_row` "inserts `('', '', '', 'unknown', 'inferred')` with `provenance NULL`", but the test `test_commit_inserts_capability_row_when_missing` asserts `provenance == "static"` and `description_provenance == "llm"`.
- Where: Task 2 Interfaces (`_ensure_capability_row(con, slug) -> bool` description) vs. Task 2 Step 1 test `assert cap == ("path", "static", "llm")`.
- Why it matters: The placeholder row is created by `_ensure_capability_row` with `provenance NULL`; then `write_commit` presumably updates it with the proposal's `provenance` (which the test's `_patch_pipeline` fixture must supply as `"static"`). If `write_commit` only UPDATEs existing rows and the placeholder was just INSERTed, the UPDATE path must run for the newly-inserted row too. The spec never states that `write_commit` re-reads and updates the placeholder it just created — it only says "Call it at the top of the per-row loop in `_persist_sanity` and in `write_commit`; in both, `continue` when the slug has no `cli` row." That `continue` semantics is ambiguous: does `continue` skip the update, or only skip the insert?
- Suggested fix: Clarify in the Interfaces block that `_ensure_capability_row` returns True and the caller proceeds to UPDATE the (now-existing) row with the proposal's fields; only the "slug not in cli" case `continue`s. Then make the test's expected `provenance` match the fixture's proposal value explicitly (state what `_patch_pipeline` returns for `provenance`).
- Confidence: high

### [IMPORTANT] `--from-proposals` skips `run_pipeline` but the spec never says how `sanity_fail_rate` is computed from the loaded report
- What: Task 2 Interfaces says `--from-proposals` "still runs `_run_calibration()` and the fail-rate gate from the loaded report", but the shipped `SANITY_FAILURE_THRESHOLD = 0.10` gate presumably compares `sanity_fail_rate` against the threshold. The spec doesn't say whether the fail rate is `fails / len(report)` or `fails / total_rows`, nor whether `total_rows` comes from the report or from a fresh `cli` count.
- Where: Task 2 Interfaces, `main` bullet: "`sanity_fail_rate` from the loaded report, then fall through to the existing two REFUSED gates".
- Why it matters: If the reviewed report was generated against a 612-row corpus but the live DB has drifted (a CLI added between Task 4 and Task 5), the fail-rate denominator is ambiguous. A reviewer/operator reading the gate output can't tell whether the gate is measuring the reviewed corpus or the current one. This is exactly the "what the operator reviewed is not what gets written" failure mode Task 2 is trying to close — but the gate re-derivation reintroduces it.
- Suggested fix: State explicitly: `sanity_fail_rate = sum(1 for r in report if not r["ok"]) / len(report)`, and add a guard that `len(report) == count(cli WHERE enabled=1)` at commit time, refusing otherwise (or logging the delta). Pin it in a test.
- Confidence: medium

### [IMPORTANT] Task 3's `PRESERVED_PROVENANCE` includes `"static"` but the design's provenance vocabulary is not shown to include it
- What: Task 3 introduces `PRESERVED_PROVENANCE = ("manual", "static", "llm")` and `description_provenance` values `"llm"`. The Global Constraints section only names `provenance = 'manual'` as protected and `confidence = 'inferred'` for backfilled rows. `"static"` and `"llm"` as `provenance` values are not defined anywhere in the spec.
- Where: Task 3 Interfaces (`PRESERVED_PROVENANCE = ("manual", "static", "llm")`) vs. Global Constraints ("Provenance guard: a capability row with `provenance = 'manual'` is never overwritten").
- Why it matters: The writer (Task 2) inserts `provenance NULL` placeholders and the test expects `provenance = "static"`. If `"static"` is a real provenance value the extractor emits, the spec should say so; if it's invented for this plan, the `populate()` guard is protecting a value that nothing writes. Either way, a reader can't tell whether `"static"` is a shipped vocabulary term or a new one this plan introduces.
- Suggested fix: Add one line to Global Constraints defining the provenance vocabulary (`manual | static | llm | NULL`) and cite where `"static"` comes from (the extractor? the July plan?). If `"static"` is new, say so and note it's a schema-vocabulary extension.
- Confidence: medium

### [IMPORTANT] Task 4 Step 4's `prose` count uses `" " in p["description"]` but AC-02 uses `LIKE '% %'` — these diverge on newlines/tabs
- What: AC-02 is defined as "description contains a space and no `Error`" and the Baseline table uses `LIKE '% %' AND NOT LIKE '%Error%'`. Task 4 Step 4's Python check uses `" " in p["description"] and "Error" not in p["description"]`. SQL `LIKE '% %'` matches any single space character; Python `" " in s` matches the same. But `NOT LIKE '%Error%'` is case-sensitive in SQLite by default, while `"Error" not in s` is also case-sensitive — so those agree. The divergence is subtler: SQL `LIKE` treats `%` and `_` as wildcards in the *pattern*, not the value, so they agree on the value side. However, the Baseline table's prose predicate is scoped to `enabled = 1`, while Task 4 Step 4 iterates all proposals — which after Task 2's `_fetch_all_cli_rows` fix are all enabled, so this is consistent. The real gap: Task 4 Step 4 counts `prose` over `backfill_proposals.jsonl`, but AC-02 is measured against the *live DB after commit* in Task 5 Step 3. A proposal whose description is prose but whose write is skipped (e.g., a `manual`-provenance row the writer refuses to overwrite) inflates the Step 4 estimate.
- Where: Task 4 Step 4 (`prose = sum(1 for p in P if " " in p["description"] and "Error" not in p["description"])`) vs. AC-02 and Task 5 Step 3's SQL.
- Why it matters: The operator gate in Task 4 Step 5 is justified by "prose=<n>/612" from the proposals file. If the writer will skip some of those rows (manual provenance, or slugs that vanished between dry run and commit), the number the operator approves is not the number that lands. AC-05 says no field changes before resolution, but nothing pins the proposals-to-DB delta.
- Suggested fix: In Task 4 Step 4, also compute `prose_writable = sum(1 for p in P if " " in p["description"] and "Error" not in p["description"] and p["slug"] not in manual_slugs)` where `manual_slugs` is queried from the live DB's `provenance = 'manual'` rows. Report both numbers in the DECISIONS entry.
- Confidence: medium

### [IMPORTANT] Task 5 Step 2's backup filename uses `git rev-parse --short HEAD` but the backup is taken *before* the commit, so the SHA is the pre-commit HEAD — the `ls` check is correct but the naming convention is fragile
- What: `backup_db` is called inside `main` before `write_commit`; the spec's `ls -la ~/.hermes/cli-registry.db.bak-$(git rev-parse --short HEAD)` runs *after* the commit command returns, so `HEAD` is still the pre-commit SHA (the commit is a DB write, not a git commit). This works, but only because Task 5 Step 2 does not `git commit` between the backup and the `ls`. If a future edit inserts a `git commit` there, the check silently passes against the wrong file.
- Where: Task 5 Step 2, `ls -la ~/.hermes/cli-registry.db.bak-$(git rev-parse --short HEAD)`.
- Why it matters: The backup is the only rollback artifact for the first live write. A check that can silently validate the wrong file is a weak gate on the highest-stakes step.
- Suggested fix: Capture the SHA before the commit command: `SHA=$(git rev-parse --short HEAD); .venv/bin/python -m tools.backfill_capabilities ... ; ls -la ~/.hermes/cli-registry.db.bak-$SHA`. Or have `backup_db` print the backup path and grep the command output for it.
- Confidence: medium

### [IMPORTANT] Task 1 Step 3's "stop and report" threshold (`cli` row count below 600, `manual` count other than 12) is not justified and may be too tight
- What: Task 1 Step 3 says "a `cli` row count below 600 or a `manual` count other than 12 is not: stop and report before continuing." The Baseline table records 636 `cli` rows / 612 enabled and 12 `manual`. The spec doesn't say why 600 is the floor or why `manual` must be exactly 12.
- Where: Task 1 Step 3, "a `cli` row count below 600 or a `manual` count other than 12 is not: stop and report".
- Why it matters: If a legitimate re-register or a manual capability edit lands between plan-writing and Task 1 execution (the plan is dated 2026-10-18 and the DB is live), the operator gets a spurious stop. Conversely, a `manual` count of 13 could be a *good* sign (someone added a manual row) that the plan treats as a failure. The threshold encodes an assumption about DB stability that isn't stated.
- Suggested fix: Either justify the thresholds (e.g., "600 = 636 − 5% drift tolerance; 12 = the count at plan-writing time, any change means a manual edit landed and the operator should review") or soften to "report the delta and proceed unless the operator says otherwise."
- Confidence: medium

### [NIT] Task 2 Step 2's expected-failure list omits `test_persist_sanity_creates_placeholder_row_for_cli_without_capability`
- What: Step 2 says "The others FAIL: `AttributeError: _ensure_capability_row`, `total_rows == 3`, `row is None`, and argparse rejecting `--from-proposals`." The `row is None` covers `test_persist_sanity_creates_placeholder_row_for_cli_without_capability`, but the `-k` filter in Step 2 is `"disabled or placeholder or unknown_slug or inserts_capability or from_proposals or fence"` — `placeholder` matches the test name, good. But `test_ensure_capability_row_refuses_unknown_slug` matches `unknown_slug`, and `test_commit_from_proposals_ignores_slug_not_in_cli` matches `from_proposals`. All 8 new tests are covered. No issue — but the mapping from failure mode to test is loose enough that a reader can't verify coverage without cross-referencing.
- Where: Task 2 Step 2.
- Why it matters: Minor; the `-k` filter is correct but the prose doesn't enumerate which test fails how.
- Suggested fix: List the 8 tests and their expected failure mode in a table.
- Confidence: high

### [NIT] Task 3 Step 2's expected failure for `test_populate_preserves_backfilled_capability_row` is `TypeError` on `description_provenance`, but that test doesn't pass `description_provenance`
- What: `test_populate_preserves_backfilled_capability_row` constructs `Capability(..., provenance="llm")` with no `description_provenance` argument. The `TypeError` on `description_provenance` would come from `test_populate_keeps_description_when_backfilled`, which does pass it. The spec's Step 2 says "the first two FAIL (`TypeError` on `description_provenance`, then provenance `None` / description overwritten once the model has the field)" — the parenthetical maps the first failure to the first test, which is wrong.
- Where: Task 3 Step 2.
- Why it matters: Cosmetic; a reader following the expected-failure list will be confused when the first test fails with an assertion error (provenance `None`), not a `TypeError`.
- Suggested fix: Reword: "the first FAILS on the provenance assertion (`None != 'llm'`); the second FAILS with `TypeError` on `description_provenance`."
- Confidence: high

### [NIT] Task 4 Step 3's `tail -14` assumes the summary JSON is exactly 14 lines
- What: "Run: `tail -14 ~/.local/state/a2a-cli-registry/backfill-dryrun-*.log`" — the summary JSON's line count is not pinned anywhere.
- Where: Task 4 Step 3.
- Why it matters: If the summary is 12 or 16 lines, the operator sees a truncated or padded view. Minor, but this is the gate-reading step.
- Suggested fix: Use `tail -n 50` or `grep -A100 '"elapsed_seconds"'` or `python -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read().splitlines()[-1]), indent=2))'`.
- Confidence: high

### [NIT] Task 5 Step 3's expected `third ≥ 551 (90 % of 612)` — 90% of 612 is 550.8, so 551 is correct, but the AC-04 wording says "≥ 90 %" which would be 550.8 → 551 rows. Consistent, but the arithmetic is worth pinning.
- What: AC-04: "`sanity_ok IS NOT NULL` on ≥ 90 % of enabled CLIs' capability rows." Task 5 Step 3 expects `third ≥ 551`. 0.90 × 612 = 550.8, so ≥ 551 is the correct integer floor. No error — flagging for the record.
- Where: AC-04 vs. Task 5 Step 3.
- Why it matters: None; the arithmetic is right. Noting so the co-reviewer doesn't flag it as a mismatch.
- Suggested fix: None.
- Confidence: high

### [NIT] Review Focus item 5 cites `~/projects/00_Governance/scripts/register_cli.py:181` but the context collector reports that path as MISSING
- What: Review Focus item 5 says "`register_cli.py` re-registering an existing slug rewrites its description (`~/projects/00_Governance/scripts/register_cli.py:181`)". The context collector's grounding table lists `~/projects/00_Governance/scripts/register_cli.py:181` as MISSING and `register_cli.py` (bare filename) as MISSING.
- Where: Review Focus item 5.
- Why it matters: The spec cites a file that the grounding layer could not find. Either the path is wrong (maybe it's `bin/register_cli.py` or a different subdir) or the file was moved/removed. The claim "carried to phase 1, not fixed here" rests on this citation.
- Suggested fix: Verify the path and correct it, or note that the file has moved and cite the current location. If the file genuinely doesn't exist, the carried-forward risk may be moot.
- Confidence: medium (the collector may have missed it; `~/projects/00_Governance` has 2735 entries and the collector only checked exact paths)

### [NIT] Task 1 Step 1's FOUNDATIONS.md entry cites the 07-03 plan, not this plan
- What: The single entry is `- capability map with real can-do descriptions | open | docs/superpowers/plans/2026-07-03-capability-backfill.md`. But this plan (2026-10-18) is the one that closes the foundation. The 07-03 plan's Task 7 is executed *by* this plan.
- Where: Task 1 Step 1.
- Why it matters: The foundation's "evidence" pointer points at a plan whose checkboxes were never ticked (per Task 5 Step 5's own note: "Checkboxes below were never ticked and are left as written"). A reader following the pointer lands on a plan that looks incomplete. Minor, but it's the artifact the operator will open to verify the foundation.
- Suggested fix: Point at this plan (`docs/superpowers/plans/2026-10-18-capability-map-phase0.md`) or list both.
- Confidence: medium

## Self-flagged uncertainty

- **Task 2's `_patch_pipeline` fixture contents**: I don't have the fixture body, so I can't verify whether it returns `provenance = "static"` for the `orphan` slug (which the test expects) or something else. The CRITICAL finding about `provenance NULL` vs `"static"` assumes the interface description is accurate; if `_patch_pipeline` overrides the placeholder's provenance, the test may pass. Flagging because the interface text and the test assertion directly contradict.
- **`description_provenance` column existence at Task 2 time**: I'm inferring from Task 3's Interfaces note ("schema from `SQLModel.metadata.create_all`, so the new model field appears automatically") that the column does not exist until Task 3. If the `drifted_db` fixture uses a hand-written schema rather than `create_all`, the column might exist earlier — but Task 3's note strongly implies `create_all`.
- **`register_cli.py:181` path**: The context collector reports MISSING, but it only checked exact paths and the repo has 2735 entries. The file may exist under a different name or the collector may have missed it. I did not re-explore per instructions.
- **Task 4 Step 4's `prose` count vs. AC-02**: I'm assuming the proposals file contains one row per enabled CLI after Task 2's `_fetch_all_cli_rows` fix. If `run_pipeline` emits proposals for disabled rows too (before the fix lands), the count is inflated — but Task 2 ships before Task 4, so this should be fine. Low confidence on whether any other path emits proposals for non-enabled rows.
- **`sanity_fail_rate` denominator**: I don't know the shipped `main`'s current computation. The IMPORTANT finding assumes it's `fails / total_rows`; if it's `fails / len(report)`, the ambiguity is smaller but still present for the `--from-proposals` path.
### Codex findings

## Findings — Codex

### [CRITICAL] Dry run violates the pre-approval write restriction
- What: Task 4 changes live capability data before operator approval, contradicting AC-05.
- Where: AC-05 says “no description or capability field of the live DB changes”; Task 4 says the dry run writes sanity fields and “placeholder capability rows.”
- Why it matters: Placeholder insertion writes capability fields, and sanity persistence updates existing rows before the gate. Task 5’s backup occurs after these mutations.
- Suggested fix: Run the dry run against a disposable SQLite snapshot. Persist placeholders, reviewed sanity results, descriptions, and capabilities to the live DB only after approval, with a backup taken before those writes.
- Confidence: high

### [CRITICAL] Resolving the decision as “stop” still opens the execution gate
- What: Task 5 checks that the question is no longer open without verifying that the operator approved committing.
- Where: Task 4 offers “commit from the reviewed file / tune and re-run / stop phase 0”; Task 5 Step 1 requires only `grep -c "Commit the reviewed backfill"` → `0`.
- Why it matters: Resolving the decision with either rejection option satisfies the documented execution condition. A failed decision-list command can also produce no matching output.
- Suggested fix: Retrieve the exact decision by its recorded question number, require successful retrieval, and verify both human resolution and the exact chosen outcome “commit from the reviewed file.” Every other outcome must block Task 5.
- Confidence: high

### [CRITICAL] Description protection can disappear after one populate run
- What: Task 3 preserves a backfilled description while allowing deletion of the capability row that holds its protection marker.
- Where: `test_populate_keeps_description_when_backfilled` seeds `description_provenance="llm"` without capability `provenance`; Step 3 protects capability rows only when their provenance belongs to `("manual", "static", "llm")`.
- Why it matters: A description-only backfilled row can retain its description on the first run, then lose `description_provenance` when its capability row is recreated. A subsequent populate run can overwrite that description, violating AC-06.
- Suggested fix: Carry `description_provenance` into replacement capability rows independently of capability ownership. Extend the supplied test to run populate twice and assert that both the description and its marker survive.
- Confidence: high

### [IMPORTANT] A clean working tree does not identify the approved artifacts
- What: Task 5 verifies that the JSONL files match current HEAD, not that they match the versions the operator reviewed.
- Where: Task 5 consumes files “at the HEAD the operator reviewed,” but Step 1 checks only `git status --porcelain backfill_proposals.jsonl sanity_report.jsonl`.
- Why it matters: Another commit can replace either file while leaving the working tree clean, allowing unreviewed content to be written under an earlier approval.
- Suggested fix: Record the Task 4 artifact commit and hashes of both files in the approval record. Before writing, verify those exact hashes or load both files directly from the approved commit.
- Confidence: high

### [IMPORTANT] Reviewed-file loading does not establish sanity coverage
- What: The replay path calculates a failure rate from the sibling report without specifying validation that its verdicts cover the proposals being written.
- Where: Task 2 Step 3 defines `_load_reviewed` as reading two JSONL files and derives `sanity_fail_rate` “from the loaded report.”
- Why it matters: An unrelated or incomplete report containing successful verdicts can satisfy the aggregate gate while proposals without verdicts are committed. Duplicate report entries can also distort the rate.
- Suggested fix: Validate schemas and unique slugs, require a verdict for every proposal being committed, and reject missing, conflicting, or unrelated verdicts. Calculate the failure rate over the validated proposal set and add negative tests for mismatched and incomplete reports.
- Confidence: high

### [IMPORTANT] Replay does not preserve the fallback-cap gate
- What: The new `--from-proposals` path omits the fallback-count evidence needed to enforce the stated `FALLBACK_CAP = 300` constraint.
- Where: Global Constraints says gates “stay as shipped,” including `FALLBACK_CAP = 300`; Task 2’s replay summary includes calibration and sanity failure rate but no fallback count.
- Why it matters: Skipping `run_pipeline` also skips any fallback limit enforced during generation. The specified replay path cannot distinguish an admissible run from artifacts produced by an over-limit run.
- Suggested fix: Persist a generation manifest containing completion status, fallback count, and artifact hashes. Require replay to validate that manifest and enforce the existing cap before backup or writes; test refusal of an over-limit manifest.
- Confidence: high

### [IMPORTANT] “Unknown purpose” descriptions count toward the prose target
- What: Both the proposal measurement and live acceptance query count the missing-source sentinel as a successful prose description.
- Where: Review Focus item 1 says to report these rows “instead of letting them count as prose”; Task 4 Step 4 counts descriptions containing a space and no `Error`, while the sentinel is `unknown purpose (<slug>)`.
- Why it matters: The 550-description threshold can pass partly because of descriptions that convey no capability. Printing a separate unknown count does not remove those rows from the success count.
- Suggested fix: Explicitly exclude the `unknown purpose` sentinel from both proposal and live prose counts, and align AC-02 with that predicate. Add a deterministic assertion that the sentinel never qualifies as usable prose.
- Confidence: high

NIT: (none).

## Self-flagged uncertainty

- The bundle omits implementation contents. Existing validation or gate helpers could mitigate the replay findings, but the specified replay path neither invokes nor requires such protections.
- The schema migration path is absent from the bundle. Adding `Capability.description_provenance` may require an upgrade for existing databases beyond the live registry; model initialization and migration excerpts are needed to assess this.
- The parent design and governance CLI implementation are not included. Their exact approval semantics cannot be verified; the approval findings above follow from the plan’s explicit options and commands.

## Triage — pre-panel round 1 (Claude, 2026-10-18 20:40)

Each finding checked against the repo at `3edf844` before the verdict. "Applied" edits are in the task text above.

**DeepSeek**

1. CRITICAL `description_provenance` missing at Task 2 time — **ignored, false premise.** `ensure_provenance_columns` (`tools/backfill_capabilities.py:74`) adds both provenance columns via guarded `ALTER TABLE` and `main` calls it before anything else (`:327`); the `drifted_db` fixture deliberately omits them to exercise that path (`tests/test_backfill_capabilities.py:211`).
2. CRITICAL `provenance NULL` vs `"static"` — **ignored as a contradiction, applied as a clarity gap.** `_patch_pipeline` returns `provenance: "static"` (`:116`) and the shipped `write_commit` updates any row whose provenance is `None`/`static`/`llm` (`:299`), so the placeholder is overwritten with the proposal's value. The Interfaces block now states the two `False` cases and the fall-through explicitly.
3. IMPORTANT fail-rate denominator — **applied.** `sanity_fail_rate = fails / len(report)` over the validated report, matching `run_pipeline` (`:234`); coverage is enforced by `_load_reviewed` (see Codex 5).
4. IMPORTANT provenance vocabulary undefined — **applied.** One line added to Global Constraints; `static`/`llm` are shipped values, not new.
5. IMPORTANT proposals count vs landed count — **applied** together with Codex 7: Task 4 Step 4 reports `prose_writable` (excludes `manual` descriptions and the sentinel) and the DECISIONS question records it.
6. IMPORTANT backup SHA captured after the run — **applied.** `SHA=$(git rev-parse --short HEAD)` before the command.
7. IMPORTANT Task 1 Step 3 thresholds unjustified — **applied**, as a parenthetical giving the reason for each.
8. NIT failure-to-test mapping — **applied** inline in Step 2's expected list; no table.
9. NIT Task 3 Step 2 maps `TypeError` to the wrong test — **applied.**
10. NIT `tail -14` — **applied**: `tail -11`, the summary is nine keys plus braces (`:243-253`).
11. NIT 551 arithmetic — no action requested, none taken.
12. NIT `register_cli.py:181` reported MISSING — **ignored.** The file exists and line 181 is `description = excluded.description` inside the `ON CONFLICT(slug) DO UPDATE`; the collector resolved `~` literally.
13. NIT FOUNDATIONS entry points at the 07-03 plan — **applied**: points at this plan.

**Codex**

1. CRITICAL dry run writes to the live DB before approval (AC-05) — **applied.** Task 4 runs against a `sqlite3 .backup` snapshot; the replay path persists the reviewed sanity verdicts behind `backup_db` in Task 5, so AC-04 still lands. Test extended to assert `sanity_ok` after replay.
2. CRITICAL "stop" also opens the gate — **applied.** Task 5 Step 1 reads the superseding entry via `bin/decisions show` and requires the exact chosen text, `Decided-by: human`, and `Supersedes: Q<n> — resolved`.
3. CRITICAL description marker dies with the recreated row — **applied.** Task 3 carries `description_provenance` into the recreated `Capability`; the test runs `populate()` twice and asserts the marker.
4. IMPORTANT clean tree does not identify the reviewed artifacts — **applied.** sha256 of both files recorded in the DECISIONS question at Task 4 Step 5 and checked at Task 5 Step 1.
5. IMPORTANT replay does not validate sanity coverage — **applied.** `_load_reviewed` refuses duplicate, missing or extra verdicts; negative test added (9 new tests, was 8).
6. IMPORTANT replay skips the fallback cap — **ignored.** `run_pipeline` exits 1 before writing either jsonl file when `fallback_count > FALLBACK_CAP` (`:191-197`), so no over-cap artifact can exist for the replay to consume; the cap is a generation-time gate and the DECISIONS question records `fallback=<n>`. A generation manifest would duplicate the hash pinning from item 4.
7. IMPORTANT `unknown purpose` counts as prose — **applied.** AC-02, Task 4 Step 4 and Task 5 Step 3 all exclude the sentinel.
