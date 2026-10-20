# Capability Loop Phase 1 — Registry Hygiene Implementation Plan

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `search_clis("file:pdf")` finds `generate_pdf`, no enabled CLI has an `unknown purpose` description, and description ownership survives regeneration, discovery and re-registration on the `cli` row.

**Architecture:** Add an atomic, additive SQLite migration from the legacy capability marker to `cli.description_provenance`; use that parent marker independently of capability ownership in both registry writers and the separate Governance upsert. Extend static extraction with source-evidenced `file:<ext>` outputs and reapply those facts after LLM fallback/repair. A small, deterministic hygiene command applies those output additions to existing non-manual capabilities and disables missing-source placeholder CLIs, preserving all rows and descriptions. The catalog matcher stays unchanged.

**Tech Stack:** Python >=3.11 (registry checkout uses 3.13), SQLModel/SQLAlchemy, SQLite, Python AST, portalocker, pytest (run as `.venv/bin/python -m pytest`). Governance uses its own `.venv/bin/python` (3.14).

**Spec:** `/Users/jcords-macmini/projects-local/20_CONSIGLIERE/docs/superpowers/specs/2026-10-19-capability-loop-phases-1-3-design.md` — body sections 4, 9 and 16, US-CAPLOOP-04 only. Body sections 1–16 take precedence over the appended reviews.

---

## Scope

This is Plan B, in `/Users/jcords-macmini/projects-local/a2a-cli-registry`. Task 3 belongs to `/Users/jcords-macmini/projects-local/00_Governance` and has a separate commit there. No Consigliere implementation, feed changes, matching changes, retirement, source restoration, or general schema cleanup is included.

Rules carried verbatim into the implementing tasks:

- Spec §4: “Deletions stay in phase 4. Nothing in phases 1 to 3 removes code, rows, or files.” Task 1 leaves the legacy persisted column intact; Task 5 disables missing-source rows without deleting their records or capabilities. Moving the active model field is the specific migration required by §9, not a retirement operation.
- Spec §9: “typed output vocabulary at regeneration so `file:<ext>` searches reach backfilled producers”; Task 4 implements extraction and normalization at both regeneration stages, and Task 5 applies it to existing rows.
- Spec §9: “the 37 `unknown purpose` rows whose source files are gone”; Task 5 resolves them using an explicit missing-file check. **Correction measured 2026-10-20 (Claude review):** only 27 of the 37 sources are gone; 10 are live tools whose source still exists (`pdf-tools-safe`, `pdf-tools-redact`, `causa`, `invoice-fetcher`, `oc`, `prefab`, `artemis-launchpad`, `nk`, `coaching-make-bundle`, `coaching-publish-bundle`). Task 5 disables the 27 and gives the 10 a reviewed `manual` description instead of hiding working tools. Probe: `python3 -c` over `cli WHERE enabled=1 AND description LIKE 'unknown purpose%'` with `os.path.exists(path)` → `37 unknown enabled; 27 missing source`.
- Spec §9: “`register_cli.py:181` re-register rewrite guarded by `description_provenance`; `description_provenance` moved from `capability` to `cli`.” Tasks 1–3 implement these together.

Grounded baseline, read-only checks on 2026-10-20:

- `00_Governance/scripts/register_cli.py:23` and `core/cli/main.py:34` name `/Users/jcords-macmini/.hermes/cli-registry.db`. `sqlite3 -readonly` reports **636 CLI rows, 612 enabled, 37 enabled descriptions matching `unknown purpose%`, 614 capability rows**. This is the live DB, not a checkout-local `registry.db`.
- Live `cli` lacks `description_provenance`; live `capability` has it. Capability description markers: 600 `llm`, 12 `manual`, 2 NULL. The 12 manual markers are the protection required by registry DECISIONS Q4; copy them without inferring description ownership from capability ownership. Q7 records approval of the old reviewed phase-0 artifact, not authorization to rerun an unrestricted LLM rewrite. Q8 explicitly carries typed outputs into this phase.
- `generate_pdf` has `output_types='path'`, capability provenance `static`, description provenance `llm`. Its registered source exists at `/Users/jcords-macmini/projects/50_KETO/scripts/generate_pdf.py`; lines 372–377 construct a ReportLab canvas with a dynamic destination, and line 489 calls `c.save()`. These are producer evidence; a mention of “PDF” in a description is not.
- `core/models.py:5-43`, `core/populate.py:52-96`, `tools/backfill_capabilities.py:77-89,308-351` are the active model/writers. `core/store/db.py:7-23` only creates tables today; `create_all` does not migrate existing columns.
- `core/catalog/queries.py:71-85` already searches capability CSV fields through `core/catalog/match.py:1-38`. `core/vocabulary.py:1-22` gates graph ports, not catalog substring searches. `examples/reference-fleet/config.toml` and `demo/config.toml` already register `file:pdf`; neither needs changes.
- `docs/superpowers/plans/2026-10-18-capability-map-phase0.md`, Task 5 Step 6, documents the coarse-output failure and deferred parent-marker move. The measured missing-source facts come from `/Users/jcords-macmini/projects-local/00_Governance/HANDOVER-20_CONSIGLIERE-2026-10-19-1402.md`; do not reclassify those CLIs by guessing new descriptions.

All existing file coordinates below refer to the checkout read for this plan; subsequent tasks locate the named symbol after earlier edits shift lines. New files and new symbols are explicitly identified as new. No UNVERIFIED dependencies remain. The plan's tests and code have not been executed while authoring it.

Canonical registry test invocation: `cd /Users/jcords-macmini/projects-local/a2a-cli-registry && .venv/bin/python -m pytest <path> -q`. Task 3 uses the same command shape in Governance. Tests use the existing `db`/`clock` fixtures, `drifted_db`/`_patch_pipeline`, or Governance's `_mkdb`/`_run`/`_row`; they never touch the live DB. Existing backfill integration cases marked `needs_router` may skip; the new ownership/extraction/hygiene tests do not depend on a router. Do not count skipped integration cases as evidence of passing them.

## File structure

Paths are relative to the registry root unless prefixed with the Governance root.

| File | Responsibility |
|---|---|
| Modify `core/models.py` | Make `Cli` the active owner of description provenance. |
| Modify `core/store/migrations.py` | Atomically copy legacy description ownership exactly once without dropping data. |
| Modify `core/store/db.py` | Run that migration on the actual engine connection before ORM use, including in-memory databases. |
| Create `tests/test_description_provenance_migration.py` | Cover legacy/fresh schemas, conflicts, independent ownership and repeat migration. |
| Modify `core/populate.py` | Preserve the parent description independently of capability replacement. |
| Modify `tools/backfill_capabilities.py` | Write parent ownership independently; retain typed producer facts before sanity checks. |
| Modify `tests/test_populate.py` | Exercise discovery with parent-owned descriptions, including zero capability rows. |
| Modify `tests/test_backfill_capabilities.py` | Move existing schema assertions to `cli`; cover independent writers and regeneration stages. |
| Modify `/Users/jcords-macmini/projects-local/00_Governance/scripts/register_cli.py` | Guard only the description assignment in re-registration, using parent ownership and a legacy-schema compatibility read. **Separate repo/task/commit (Task 3).** |
| Modify `/Users/jcords-macmini/projects-local/00_Governance/tests/test_register_cli.py` | Verify curated descriptions survive explicit/harvested re-registration and metadata still updates. **Governance commit only.** |
| Modify `tools/capability_extractor.py` | Emit additive `file:<ext>` outputs from literal write destinations and saved ReportLab canvases. |
| Modify `tests/test_capability_extractor.py` | Test producer evidence, consumer negatives, typed deduplication and the observed PDF source shape. |
| Create `tools/registry_hygiene.py` | Preview/apply deterministic output regeneration and reversible missing-source disabling under one transaction. |
| Create `tests/test_registry_hygiene.py` | Exercise dry-run, backup, rollback, manual protection, idempotency and real catalog search. |
| Runtime modify `/Users/jcords-macmini/.hermes/cli-registry.db` | Apply the verified migration and hygiene changes in Task 5 only; never stage the DB. |
| Runtime create `<db-name>.hygiene-<unique>.bak` beside the selected DB | SQLite-consistent backup before any live mutation; printed by the command, never staged. |

---

## Chunk 1: Put description ownership on the parent and protect every writer

### Task 1: Add and migrate `cli.description_provenance`

Implements spec §§9 and 16 AC-03. Under §4 the old SQLite column remains as inert historical data; fresh databases have the field only on `cli`. Copy legacy description markers, never `capability.provenance`. A previously present parent column is authoritative, even when NULL. The schema addition and copy are one transaction so a crash cannot leave an added-but-unpopulated column that suppresses the copy on restart.

**Files:**
- Modify: `core/models.py:12-13,34-43`
- Modify: `core/store/migrations.py:1-39` (append the two new functions)
- Modify: `core/store/db.py:1-23` (`init_db`)
- Create: `tests/test_description_provenance_migration.py`
- Test: `tests/test_description_provenance_migration.py`

- [ ] **Step 0: Back up the live registry before any auto-migrating code lands**

`init_db` migrates on open once this task lands, so the first registry command after the commit migrates the live DB, before Task 5's own backup runs. Take the backup now:

```bash
sqlite3 /Users/jcords-macmini/.hermes/cli-registry.db ".backup '/Users/jcords-macmini/.hermes/cli-registry.db.pre-caploop04-$(date +%Y%m%d%H%M).bak'"
ls -la /Users/jcords-macmini/.hermes/cli-registry.db.pre-caploop04-*.bak
```

Expected: one backup file of roughly the live DB's size. Record its path in the implementation handoff; never stage it.

- [ ] **Step 1: Write the failing migration tests**

Create the complete test file:

```python
import sqlite3

import pytest
from sqlalchemy import text

from core.models import Cli, Capability
from core.store.db import init_db
from core.store.migrations import ensure_description_provenance


def legacy(path, *, parent=False, child=True):
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE cli (slug TEXT PRIMARY KEY, description TEXT)")
        con.execute("INSERT INTO cli VALUES ('tool', 'Keep this description.')")
        con.execute("INSERT INTO cli VALUES ('no-cap', 'No capability required.')")
        if parent:
            con.execute("ALTER TABLE cli ADD COLUMN description_provenance TEXT")
        con.execute("CREATE TABLE capability (id INTEGER PRIMARY KEY, cli_slug TEXT, provenance TEXT)")
        if child:
            con.execute("ALTER TABLE capability ADD COLUMN description_provenance TEXT")
            con.executemany(
                "INSERT INTO capability VALUES (?, 'tool', 'static', ?)",
                [(1, 'static'), (2, 'llm'), (3, 'manual')],
            )
        else:
            con.execute("INSERT INTO capability VALUES (1, 'tool', 'manual')")


def test_parent_model_owns_description_provenance():
    assert 'description_provenance' in Cli.model_fields
    assert 'description_provenance' not in Capability.model_fields


def test_migration_preserves_rows_and_manual_wins_conflicts(tmp_path):
    path = tmp_path / 'legacy.db'
    legacy(path)
    ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert con.execute('SELECT * FROM cli ORDER BY slug').fetchall() == [
            ('no-cap', 'No capability required.', None),
            ('tool', 'Keep this description.', 'manual'),
        ]
        assert con.execute('SELECT COUNT(*) FROM capability').fetchone()[0] == 3
        assert 'description_provenance' in {
            r[1] for r in con.execute('PRAGMA table_info(capability)')
        }
        con.execute("UPDATE cli SET description_provenance=NULL WHERE slug='tool'")
    ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT description_provenance FROM cli WHERE slug='tool'").fetchone() == (None,)


@pytest.mark.parametrize('marker', [None, 'manual', 'static', 'llm'])
def test_existing_parent_is_authoritative(tmp_path, marker):
    path = tmp_path / 'legacy.db'
    legacy(path, parent=True)
    with sqlite3.connect(path) as con:
        con.execute('UPDATE cli SET description_provenance=?', (marker,))
    ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT description_provenance FROM cli WHERE slug='tool'").fetchone() == (marker,)


def test_capability_owner_is_not_a_description_owner(tmp_path):
    path = tmp_path / 'legacy.db'
    legacy(path, child=False)
    ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert con.execute('SELECT description_provenance FROM cli').fetchall() == [(None,), (None,)]


@pytest.mark.parametrize(('markers', 'expected'), [
    (['static', 'llm'], 'llm'),
    ([None, 'static'], 'static'),
    ([None, None], None),
    (['future-owner'], 'future-owner'),
])
def test_migration_copies_description_markers_deterministically(tmp_path, markers, expected):
    path = tmp_path / 'legacy.db'
    legacy(path)
    with sqlite3.connect(path) as con:
        con.execute('DELETE FROM capability')
        con.executemany(
            "INSERT INTO capability (cli_slug, provenance, description_provenance) VALUES ('tool','manual',?)",
            [(marker,) for marker in markers],
        )
    ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT description_provenance FROM cli WHERE slug='tool'").fetchone() == (expected,)


def test_failure_rolls_back_column_addition_and_copy(tmp_path, monkeypatch):
    import core.store.migrations as migrations

    path = tmp_path / 'legacy.db'
    legacy(path)
    real_migrate = migrations.migrate_description_provenance

    def fail_after_copy(con):
        real_migrate(con)
        raise RuntimeError('fixture interrupted migration')

    monkeypatch.setattr(migrations, 'migrate_description_provenance', fail_after_copy)
    with pytest.raises(RuntimeError, match='interrupted migration'):
        migrations.ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert 'description_provenance' not in {r[1] for r in con.execute('PRAGMA table_info(cli)')}
        assert con.execute('SELECT COUNT(*) FROM capability').fetchone()[0] == 3


def test_missing_capability_table_is_supported(tmp_path):
    path = tmp_path / 'cli-only.db'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE cli (slug TEXT PRIMARY KEY)')
    ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert 'description_provenance' in {r[1] for r in con.execute('PRAGMA table_info(cli)')}


def test_empty_database_is_supported(tmp_path):
    path = tmp_path / 'empty.db'
    ensure_description_provenance(str(path))
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_startup_migrates_before_returning_engine(tmp_path):
    path = tmp_path / 'legacy.db'
    legacy(path)
    engine = init_db(str(path))
    try:
        with engine.connect() as con:
            assert con.execute(text("SELECT description_provenance FROM cli WHERE slug='tool'")).scalar_one() == 'manual'
    finally:
        engine.dispose()


def test_fresh_memory_schema_has_only_parent_marker():
    engine = init_db(':memory:')
    try:
        with engine.connect() as con:
            cli_cols = {r[1] for r in con.execute(text('PRAGMA table_info(cli)'))}
            cap_cols = {r[1] for r in con.execute(text('PRAGMA table_info(capability)'))}
        assert 'description_provenance' in cli_cols
        assert 'description_provenance' not in cap_cols
    finally:
        engine.dispose()
```

- [ ] **Step 2: Run the new tests and observe failure**

```bash
.venv/bin/python -m pytest tests/test_description_provenance_migration.py -q
```

Expected FAIL during collection: `ImportError: cannot import name 'ensure_description_provenance'`. This establishes the missing migration API; the tests also require the model move and startup integration.

- [ ] **Step 3: Implement the parent field and atomic migration**

In `Cli`, immediately after `description`, add:

```python
    # Independent of Capability.provenance; NULL means discovery-owned.
    description_provenance: Optional[str] = None
```

Replace the ownership comment and fields at `Capability` lines 34–43 with the complete block below; the parent field above replaces the old model field:

```python
    # Discovery preserves manual/static/llm capabilities. Regeneration may
    # refresh static/llm values, but never manual values.
    provenance: Optional[str] = None
```

Append to `core/store/migrations.py`:

```python
def migrate_description_provenance(con: sqlite3.Connection) -> None:
    """Caller owns an IMMEDIATE transaction. Never drop the legacy column."""
    if not _table_exists(con, 'cli') or _column_exists(con, 'cli', 'description_provenance'):
        return
    con.execute('ALTER TABLE cli ADD COLUMN description_provenance TEXT')
    if not _table_exists(con, 'capability') or not _column_exists(con, 'capability', 'description_provenance'):
        return
    con.execute("""
        UPDATE cli SET description_provenance = (
            SELECT c.description_provenance FROM capability AS c
            WHERE c.cli_slug = cli.slug AND c.description_provenance IS NOT NULL
            ORDER BY CASE c.description_provenance
                WHEN 'manual' THEN 0 WHEN 'llm' THEN 1 WHEN 'static' THEN 2 ELSE 3
            END, c.description_provenance
            LIMIT 1
        )
    """)


def ensure_description_provenance(db_path: str) -> None:
    con = sqlite3.connect(db_path, timeout=5.0)
    try:
        con.execute('BEGIN IMMEDIATE')
        migrate_description_provenance(con)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
```

In `core/store/db.py`, add the import:

```python
from core.store.migrations import migrate_description_provenance
```

Between engine construction and the existing `SQLModel.metadata.create_all(engine)`, insert:

```python
    connection = engine.raw_connection()
    try:
        connection.execute('BEGIN IMMEDIATE')
        migrate_description_provenance(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        engine.dispose()
        raise
    finally:
        connection.close()
```

The migration runs on the engine's own connection, so `:memory:` is not accidentally migrated through an unrelated SQLite connection. `BEGIN IMMEDIATE` serializes existence-check/copy across processes. Leave `ensure_fixed_by_column` unchanged.

- [ ] **Step 4: Run the migration tests**

```bash
.venv/bin/python -m pytest tests/test_description_provenance_migration.py tests/test_fixed_by_migration.py -q
```

Expected PASS: new migration tests plus existing fixed-by tests. Full writer compatibility is completed in Task 2; do not deploy between Tasks 1 and 2.

- [ ] **Step 5: Commit the schema change in the registry repo**

```bash
git add -- core/models.py core/store/migrations.py core/store/db.py tests/test_description_provenance_migration.py
git commit -m "feat: move description ownership to cli with additive migration" -- core/models.py core/store/migrations.py core/store/db.py tests/test_description_provenance_migration.py
```

### Task 2: Use parent ownership in discovery and regeneration

Implements spec §§9 and 16 AC-03, preserving the independent guards from registry DECISIONS Q4/Q5. A manual capability does not freeze an unowned description; a manual description does not freeze a generated capability. Description-only writes must not create a capability just to hold provenance.

**Files:**
- Modify: `core/populate.py:52-96`
- Modify: `tools/backfill_capabilities.py:20-28,77-89,308-351`
- Modify: `tests/test_populate.py:166-179`
- Modify: `tests/test_backfill_capabilities.py:174-192,211-225,435-447` and append new tests
- Test: `tests/test_populate.py`, `tests/test_backfill_capabilities.py`

- [ ] **Step 1: Write parent-ownership regression tests**

Replace `test_populate_keeps_description_when_backfilled` and its parameterization with:

```python
@pytest.mark.parametrize('marker', ['static', 'llm', 'manual'])
@pytest.mark.parametrize('has_capability', [False, True])
def test_populate_keeps_description_when_backfilled(db, clock, marker, has_capability):
    db.add(Cli(slug='tool', lang='python', description='Exports things to JSON.',
               description_provenance=marker))
    if has_capability:
        db.add(Capability(cli_slug='tool', output_types='old'))
    db.commit()
    rec = _rec('tool', ['text'], ['text'])
    rec.description = 'scripts/tool.py'
    vocab = VocabularyRegistry(registered={'text'}, aliases={})
    for _ in range(2):
        populate(db, FakeSource([rec]), [PythonAdapter()], vocab, clock)
        row = db.get(Cli, 'tool')
        assert row.description == 'Exports things to JSON.'
        assert row.description_provenance == marker
        assert db.exec(select(Capability).where(Capability.cli_slug == 'tool')).one().output_types == 'text'


def test_manual_capability_does_not_freeze_feed_description(db, clock):
    db.add(Cli(slug='tool', lang='python', description='Old description.'))
    db.add(Capability(cli_slug='tool', output_types='manual-output', provenance='manual'))
    db.commit()
    rec = _rec('tool', ['text'], ['text'])
    rec.description = 'Updated feed description.'
    populate(db, FakeSource([rec]), [PythonAdapter()],
             VocabularyRegistry(registered={'text'}, aliases={}), clock)
    assert db.get(Cli, 'tool').description == 'Updated feed description.'
    assert db.exec(select(Capability).where(Capability.cli_slug == 'tool')).one().output_types == 'manual-output'
```

Append to `tests/test_backfill_capabilities.py`, reusing its existing raw `drifted_db` fixture:

```python
@pytest.mark.parametrize('description_owner', [None, 'static', 'llm', 'manual'])
@pytest.mark.parametrize('capability_owner', [None, 'static', 'llm', 'manual'])
def test_write_commit_uses_independent_parent_and_capability_guards(
    drifted_db, description_owner, capability_owner
):
    backfill.ensure_provenance_columns(drifted_db)
    with sqlite3.connect(drifted_db) as con:
        con.execute("UPDATE cli SET description='Curated', description_provenance=? WHERE slug='csv2json'",
                    (description_owner,))
        con.execute("UPDATE capability SET output_types='old', provenance=? WHERE cli_slug='csv2json'",
                    (capability_owner,))
    backfill.write_commit(drifted_db, [{
        'slug': 'csv2json', 'description': 'Generated',
        'capability': {'input_types': ['path'], 'output_types': ['file:pdf'],
                       'intent_tags': ['generate'], 'side_effect': 'none',
                       'confidence': 'inferred', 'provenance': 'static'},
    }])
    with sqlite3.connect(drifted_db) as con:
        desc = con.execute("SELECT description, description_provenance FROM cli WHERE slug='csv2json'").fetchone()
        cap = con.execute("SELECT output_types, provenance FROM capability WHERE cli_slug='csv2json'").fetchone()
    assert desc == (('Curated', 'manual') if description_owner == 'manual' else ('Generated', 'llm'))
    assert cap == (('old', 'manual') if capability_owner == 'manual' else ('file:pdf', 'static'))


def test_description_only_commit_needs_no_capability_row(drifted_db):
    with sqlite3.connect(drifted_db) as con:
        con.execute("DELETE FROM capability WHERE cli_slug='shellwrap'")
    backfill.ensure_provenance_columns(drifted_db)
    backfill.write_commit(drifted_db, [
        {'slug': 'shellwrap', 'description': 'Runs a shell tool.', 'capability': None},
        {'slug': 'never-registered', 'description': 'Absent.', 'capability': None},
    ])
    with sqlite3.connect(drifted_db) as con:
        assert con.execute("SELECT description, description_provenance FROM cli WHERE slug='shellwrap'").fetchone() == ('Runs a shell tool.', 'llm')
        assert con.execute("SELECT COUNT(*) FROM capability WHERE cli_slug IN ('shellwrap','never-registered')").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM cli WHERE slug='never-registered'").fetchone()[0] == 0


def test_each_manual_capability_row_is_protected(drifted_db):
    backfill.ensure_provenance_columns(drifted_db)
    with sqlite3.connect(drifted_db) as con:
        con.execute("""INSERT INTO capability
            (cli_slug,intent_tags,input_types,output_types,side_effect,confidence,provenance)
            VALUES ('csv2json','','','curated','none','declared','manual')""")
    backfill.write_commit(drifted_db, [{
        'slug': 'csv2json', 'description': 'Generated',
        'capability': {'input_types': [], 'output_types': ['file:pdf'],
                       'intent_tags': [], 'side_effect': 'none',
                       'confidence': 'inferred', 'provenance': 'static'},
    }])
    with sqlite3.connect(drifted_db) as con:
        assert con.execute("SELECT output_types, provenance FROM capability WHERE cli_slug='csv2json' ORDER BY id").fetchall() == [('file:pdf', 'static'), ('curated', 'manual')]
```

The DELETE above is fixture setup on a temporary test DB, not a live retirement operation.

- [ ] **Step 2: Run the regression tests and observe failure**

```bash
.venv/bin/python -m pytest tests/test_populate.py tests/test_backfill_capabilities.py -q -k 'keeps_description_when_backfilled or manual_capability_does_not_freeze or independent_parent or description_only_commit or each_manual'
```

Expected FAIL: `AttributeError` accessing the removed capability description field and/or `sqlite3.OperationalError: no such column: description_provenance` on `cli` in the old raw migration path. No router is required by the selected tests.

- [ ] **Step 3: Implement independent parent guards and update old schema assertions**

In `core/populate.py`, replace the block from `old_caps = ...` through `cli.description = rec.description` with:

```python
        old_caps = session.exec(
            select(Capability).where(Capability.cli_slug == rec.slug)
        ).all()
        cli = session.get(Cli, rec.slug)
        if cli is None:
            cli = Cli(slug=rec.slug)
            added += 1
        cli.lang = rec.lang
        cli.path = rec.path
        cli.bucket = rec.bucket
        cli.project = rec.project
        if cli.description_provenance not in PRESERVED_PROVENANCE:
            cli.description = rec.description
```

Replace its capability replacement block at lines 79–96 with:

```python
        if not any(c.provenance in PRESERVED_PROVENANCE for c in old_caps):
            for old in old_caps:
                session.delete(old)
            session.add(Capability(
                cli_slug=rec.slug,
                intent_tags=','.join(merged.intent_tags),
                input_types=','.join(merged.input_types),
                output_types=','.join(merged.output_types),
                side_effect=merged.side_effect,
                confidence=merged.confidence,
            ))
```

This changes where the guard reads ownership. Existing population/removal semantics are not changed; do not run population against the live fleet for this hygiene task.

In `tools/backfill_capabilities.py`, add:

```python
from core.store.migrations import ensure_description_provenance
```

Replace `ensure_provenance_columns` completely:

```python
def ensure_provenance_columns(db_path: str) -> None:
    ensure_description_provenance(db_path)
    con = sqlite3.connect(db_path)
    try:
        _add_column_guarded(con, 'capability', 'provenance', 'TEXT')
        _add_column_guarded(con, 'capability', 'sanity_ok', 'INTEGER')
        _add_column_guarded(con, 'capability', 'sanity_reason', 'TEXT')
        _add_column_guarded(con, 'capability', 'sanity_checked_at', 'REAL')
    finally:
        con.close()
```

Replace `write_commit` completely (its caller still migrates behind the backup and lock):

```python
def write_commit(db_path: str, proposals: list[dict]) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.execute('BEGIN IMMEDIATE')
        for p in proposals:
            slug, description, capability = p['slug'], p['description'], p['capability']
            if not _cli_exists(con, slug):
                continue
            con.execute("""
                UPDATE cli SET description=?, description_provenance='llm'
                WHERE slug=? AND (description_provenance IS NULL
                                  OR description_provenance IN ('static','llm'))
            """, (description, slug))
            if capability is None:
                continue
            _ensure_capability_row(con, slug)
            con.execute("""
                UPDATE capability SET input_types=?, output_types=?, intent_tags=?,
                    side_effect=?, confidence=?, provenance=?
                WHERE cli_slug=? AND (provenance IS NULL OR provenance IN ('static','llm'))
            """, (
                ','.join(capability['input_types']), ','.join(capability['output_types']),
                ','.join(capability['intent_tags']), capability['side_effect'],
                capability['confidence'], capability['provenance'], slug,
            ))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
```

Update the existing tests that still address the old location. In `test_manual_description_provenance_protected_independently_of_capability`, replace only its marker-setting statement with:

```python
    con.execute("UPDATE cli SET description_provenance='manual' WHERE slug='csv2json'")
```

Replace `test_both_provenance_columns_auto_added_when_missing` completely:

```python
def test_both_provenance_columns_auto_added_when_missing(drifted_db):
    backfill.ensure_provenance_columns(drifted_db)
    with sqlite3.connect(drifted_db) as con:
        cli_cols = {r[1] for r in con.execute('PRAGMA table_info(cli)')}
        cap_cols = {r[1] for r in con.execute('PRAGMA table_info(capability)')}
    assert 'description_provenance' in cli_cols
    assert 'provenance' in cap_cols
    assert 'description_provenance' not in cap_cols
```

Replace `test_commit_inserts_capability_row_when_missing`, retaining its integration marker:

```python
@needs_router
def test_commit_inserts_capability_row_when_missing(drifted_db, monkeypatch, tmp_path):
    with sqlite3.connect(drifted_db) as con:
        _insert_cli(con, 'orphan')
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.main(['--db', drifted_db, '--commit'])
    with sqlite3.connect(drifted_db) as con:
        cap = con.execute("SELECT input_types, provenance FROM capability WHERE cli_slug='orphan'").fetchone()
        desc = con.execute("SELECT description, description_provenance FROM cli WHERE slug='orphan'").fetchone()
    assert cap == ('path', 'static')
    assert desc == ('A test CLI that converts things.', 'llm')
```

- [ ] **Step 4: Run the relevant writer and migration tests**

```bash
.venv/bin/python -m pytest tests/test_description_provenance_migration.py tests/test_populate.py tests/test_backfill_capabilities.py tests/test_description_regenerator.py -q
```

Expected PASS for all collected non-skipped tests. Existing router integration cases may skip when the router is unavailable; all new ownership cases must pass, not skip. Prose regeneration's missing-source sentinel contract remains unchanged.

- [ ] **Step 5: Commit the writer changes in the registry repo**

```bash
git add -- core/populate.py tools/backfill_capabilities.py tests/test_populate.py tests/test_backfill_capabilities.py
git commit -m "fix: preserve cli description ownership across registry writers" -- core/populate.py tools/backfill_capabilities.py tests/test_populate.py tests/test_backfill_capabilities.py
```

### Task 3: Guard the Governance re-registration upsert in its own repo

Implements spec §§9 and 16 AC-03 at the actual `ON CONFLICT(slug) DO UPDATE` assignment, currently line 181. This is a **separate Governance change and commit**. Parent ownership wins whenever the parent column exists. A legacy-schema compatibility read protects existing curated descriptions before the registry migration is applied; it never adds a column or writes a legacy marker. A truly old database with neither marker keeps its existing upsert behavior.

**Files (all in `/Users/jcords-macmini/projects-local/00_Governance`):**
- Modify: `scripts/register_cli.py:130-205` (new helper before `upsert`, guarded SQL inside it)
- Modify: `tests/test_register_cli.py:1-54,206-210` (reuse existing helpers; append tests)
- Test: `tests/test_register_cli.py`

- [ ] **Step 1: Write the failing re-registration tests in Governance**

Append to `tests/test_register_cli.py`:

```python
@pytest.mark.parametrize('marker', [None, 'manual', 'static', 'llm'])
@pytest.mark.parametrize('explicit', [False, True])
def test_reregister_uses_parent_description_owner(tmp_path, marker, explicit):
    db = _mkdb(tmp_path)
    first = _run(db, '--slug', 'owned', '--path', '/old/owned.py',
                 '--description', 'Curated description.', '--a2a-invokable',
                 '--health-status', 'healthy', '--not-standalone')
    assert first.returncode == 0 and 'WARNING' not in first.stderr
    with sqlite3.connect(db) as con:
        con.execute('ALTER TABLE cli ADD COLUMN description_provenance TEXT')
        con.execute("UPDATE cli SET description_provenance=?, enabled=0 WHERE slug='owned'", (marker,))
        # A stale child marker must not override an authoritative parent NULL.
        con.execute('CREATE TABLE capability (cli_slug TEXT, provenance TEXT, description_provenance TEXT)')
        con.execute("INSERT INTO capability VALUES ('owned','manual','manual')")
    script = _script(tmp_path, 'new.py', '"""Harvested replacement."""\n')
    extra = ('--description', 'Explicit replacement.') if explicit else ()
    result = _run(db, '--slug', 'owned', '--path', script, '--project', 'new-project', *extra)
    assert result.returncode == 0 and 'WARNING' not in result.stderr
    expected = 'Explicit replacement.' if explicit else 'Harvested replacement.'
    if marker is not None:
        expected = 'Curated description.'
    assert _row(db, 'owned', 'description, description_provenance') == (expected, marker)
    assert _row(db, 'owned', 'path, project, enabled, a2a_invokable, health_status, not_standalone') == (
        script, 'new-project', 0, 1, 'healthy', 1,
    )
    assert json.loads(_row(db, 'owned', 'launch_spec')[0])['script_path'] == script


@pytest.mark.parametrize('marker', [None, 'manual', 'static', 'llm'])
def test_reregister_protects_legacy_description_owner_without_migrating(tmp_path, marker):
    db = _mkdb(tmp_path)
    _run(db, '--slug', 'legacy', '--path', '/old.py', '--description', 'Curated')
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE capability (cli_slug TEXT, provenance TEXT, description_provenance TEXT)')
        con.execute("INSERT INTO capability VALUES ('legacy','manual',?)", (marker,))
    result = _run(db, '--slug', 'legacy', '--path', '/new.py', '--description', 'Replacement')
    assert result.returncode == 0 and 'WARNING' not in result.stderr
    assert _row(db, 'legacy', 'description, path') == (
        'Curated' if marker is not None else 'Replacement', '/new.py',
    )
    with sqlite3.connect(db) as con:
        assert 'description_provenance' not in {r[1] for r in con.execute('PRAGMA table_info(cli)')}
```

The existing `test_upsert_is_idempotent`, harvesting tests, and fail-open test cover fresh/markerless schemas and new rows. New tests assert data as well as process exit status because this script intentionally returns zero on a skipped registration.

- [ ] **Step 2: Run the new tests in Governance and observe failure**

```bash
cd /Users/jcords-macmini/projects-local/00_Governance
.venv/bin/python -m pytest tests/test_register_cli.py -q -k 'reregister_uses_parent or reregister_protects_legacy'
```

Expected FAIL: curated-marker cases compare `'Explicit replacement.'`, `'Harvested replacement.'` or `'Replacement'` against the expected curated description. NULL-owner cases continue to refresh.

- [ ] **Step 3: Implement the guarded assignment without changing registration flags**

Add this complete helper immediately before `upsert`:

```python
def _description_update_sql(con: sqlite3.Connection) -> str:
    """SQL fragments are fixed constants; schema names never come from input."""
    cli_columns = {row[1] for row in con.execute('PRAGMA table_info(cli)')}
    if 'description_provenance' in cli_columns:
        protected = "cli.description_provenance IN ('manual','static','llm')"
    else:
        capability_columns = {row[1] for row in con.execute('PRAGMA table_info(capability)')}
        if 'description_provenance' not in capability_columns:
            return 'excluded.description'
        protected = """EXISTS (
            SELECT 1 FROM capability AS c
            WHERE c.cli_slug=cli.slug
              AND c.description_provenance IN ('manual','static','llm')
        )"""
    return f'CASE WHEN {protected} THEN cli.description ELSE excluded.description END'
```

Inside `upsert`, replace the complete `con.execute(...)` call at lines 165–199 with:

```python
            description_update = _description_update_sql(con)
            con.execute(
                f"""INSERT INTO cli
                   (slug, lang, bucket, project, path, launch_spec, description,
                    source_class, health_cmd, health_status, health_checked_at,
                    fixed_by, enabled, a2a_invokable, source_run_id,
                    last_seen_at, updated_at, not_standalone)
                   VALUES (:slug, :lang, NULL, :project, :path, :launch_spec,
                           :desc, 'manual-register', NULL,
                           COALESCE(:health, 'unknown'), NULL,
                           NULL, 1, COALESCE(:a2a, 0), 'post-commit-register',
                           :now, :now, COALESCE(:notstandalone, 0))
                   ON CONFLICT(slug) DO UPDATE SET
                     lang = excluded.lang,
                     project = excluded.project,
                     path = excluded.path,
                     launch_spec = excluded.launch_spec,
                     description = {description_update},
                     last_seen_at = excluded.last_seen_at,
                     updated_at = excluded.updated_at,
                     a2a_invokable = COALESCE(:a2a, cli.a2a_invokable),
                     health_status = COALESCE(:health, cli.health_status),
                     not_standalone = COALESCE(:notstandalone, cli.not_standalone)""",
                {'slug': slug, 'lang': lang, 'project': project, 'path': path,
                 'launch_spec': launch_spec, 'desc': desc, 'now': now,
                 'a2a': None if a2a_invokable is None else int(a2a_invokable),
                 'health': health_status,
                 'notstandalone': None if not_standalone is None else int(not_standalone)},
            )
```

Leave the surrounding connection/commit/close and fail-open exception envelope intact. Existing explicit `--description` updates unowned rows; it is not an implicit force override of a curated marker. New rows remain unowned, preserving this CLI's existing semantics. No new flag, registry package dependency, or Governance migration is needed.

- [ ] **Step 4: Run the Governance registration tests**

```bash
.venv/bin/python -m pytest tests/test_register_cli.py -q
```

Expected PASS: all registration tests, including current launch-spec, health, a2a, and standalone tri-state behavior. This targeted command follows this plan's explicit test scope.

- [ ] **Step 5: Commit only the Governance change in Governance**

```bash
git add -- scripts/register_cli.py tests/test_register_cli.py
git commit -m "fix: preserve curated registry descriptions on re-registration" -- scripts/register_cli.py tests/test_register_cli.py
```

Return to the registry root for every remaining task. No Governance files belong in a registry commit.

---

## Chunk 2: Regenerate typed producer outputs

### Task 4: Add source-evidenced `file:<ext>` ports and preserve them through regeneration

Implements spec §9's “typed output vocabulary at regeneration so `file:<ext>` searches reach backfilled producers” and §16 AC-01. Keep `path`/`json`/`text` for compatibility and add typed tokens. Recognize literal writer destinations generally and ReportLab canvas construction followed by saving in the same scope, matching the verified `generate_pdf` implementation. Do not infer a producer from input filenames, a PDF-reader import, a slug or prose. Do not change §6.3 matching semantics or graph admission.

**Files:**
- Modify: `tools/capability_extractor.py:7-10,217-270` (new helpers before `extract_outputs`, additive typed outputs before stdout inference)
- Modify: `tools/backfill_capabilities.py:212-219,249-256` (normalize after fallback and before repair recheck)
- Modify: `tests/test_capability_extractor.py:1-5,518-525` (append tests after the existing output tests)
- Modify: `tests/test_backfill_capabilities.py:109-124,533` (reuse helpers; append tests)
- Test: `tests/test_capability_extractor.py`, `tests/test_backfill_capabilities.py`

- [ ] **Step 1: Write typed extraction and regeneration regression tests**

Append to `tests/test_capability_extractor.py`:

```python
@pytest.mark.parametrize(('source', 'token'), [
    ('open("out.PDF", "wb").write(b"pdf")', 'file:pdf'),
    ('Path("out.csv").write_text("a,b")', 'file:csv'),
    ('Path("out.png").write_bytes(b"png")', 'file:png'),
    ('presentation.save("deck.pptx")', 'file:pptx'),
    ('plot.savefig("chart.svg")', 'file:svg'),
    ('open(file="out.json", mode="x").write("{}")', 'file:json'),
])
def test_typed_output_from_literal_writer_destination(source, token):
    outputs = extract_outputs(source)
    assert token in outputs
    assert 'path' in outputs
    assert outputs.count(token) == 1


def test_generate_pdf_reportlab_shape_has_typed_output():
    source = '''
def render(output_path):
    from reportlab.pdfgen import canvas as rl_canvas
    c = rl_canvas.Canvas(str(output_path), pagesize=A4)
    c.drawString(1, 1, "hello")
    c.save()
'''
    assert extract_outputs(source) == ['path', 'file:pdf']
    assert extract_capability('generate_pdf', 'Renders a document.', source)['output_types'] == ['path', 'file:pdf']


@pytest.mark.parametrize('source', [
    '"""Convert a PDF input to text."""\nprint(open("input.pdf").read())',
    'from pypdf import PdfReader\nprint(PdfReader("in.pdf").pages)',
    'from reportlab.pdfgen import canvas\nc = canvas.Canvas("out.pdf")',
    'from reportlab.pdfgen import canvas\ndef first():\n c=canvas.Canvas("a.pdf")\ndef second():\n c.save()',
    'def broken(:',
])
def test_consumers_unsaved_canvases_and_unrelated_scopes_do_not_emit_pdf(source):
    assert 'file:pdf' not in extract_outputs(source)


def test_output_normalization_is_additive_and_does_not_mutate_input():
    from tools.capability_extractor import with_typed_outputs
    original = {'output_types': ['path', 'file:pdf'], 'provenance': 'llm'}
    result = with_typed_outputs(original, 'open("out.pdf", "wb")')
    assert result == original
    assert result is not original
    assert original['output_types'] == ['path', 'file:pdf']
    assert with_typed_outputs(None, 'open("out.pdf", "wb")') is None
```

Append to `tests/test_backfill_capabilities.py`:

```python
@pytest.mark.parametrize('fallback', [False, True])
@pytest.mark.parametrize('repair', [False, True])
def test_pipeline_keeps_typed_outputs_before_each_sanity_check(
    drifted_db, monkeypatch, tmp_path, fallback, repair
):
    coarse = {'input_types': [] if fallback else ['path'], 'output_types': ['path'],
              'intent_tags': ['generate'], 'side_effect': 'none',
              'confidence': 'inferred', 'provenance': 'static'}
    _patch_pipeline(monkeypatch, cap_result=coarse)
    monkeypatch.setattr(backfill, '_read_source', lambda path: 'open("out.pdf", "wb")')
    monkeypatch.setattr(backfill, '_run_calibration', lambda: (True, 'unit fixture'))
    monkeypatch.setattr(backfill.capability_llm_fallback, 'infer_capability_llm',
                        lambda *args: {**coarse, 'input_types': ['path'], 'provenance': 'llm'})
    seen = []

    def check(slug, description, capability):
        if slug != 'csv2json':
            return {'ok': True, 'reason': ''}
        seen.append(list(capability['output_types']))
        return {'ok': not repair or description == 'Repaired', 'reason': 'repair fixture'}

    monkeypatch.setattr(backfill.sanity_check, 'check_row', check)
    monkeypatch.setattr(backfill.capability_repair, 'repair_row', lambda slug, *args: {
        'slug': slug, 'description': 'Repaired',
        'capability': {**coarse, 'output_types': ['path'], 'provenance': 'llm'},
    })
    monkeypatch.chdir(tmp_path)
    result = backfill.run_pipeline(drifted_db, persist_sanity=False)
    proposal = next(p for p in result['proposals'] if p['slug'] == 'csv2json')
    assert proposal['capability']['output_types'] == ['path', 'file:pdf']
    assert seen == [['path', 'file:pdf']] * (2 if repair else 1)
    assert result['summary']['fallback_count'] == int(fallback)
    assert result['summary']['repaired_count'] == int(repair)
    backfill.ensure_provenance_columns(drifted_db)
    backfill.write_commit(drifted_db, [proposal])
    with sqlite3.connect(drifted_db) as con:
        assert con.execute("SELECT output_types FROM capability WHERE cli_slug='csv2json'").fetchone() == ('path,file:pdf',)
```

The calibration stub is confined to this deterministic pipeline unit test. The production calibration function, thresholds, proposal replay and judge gates remain intact.

- [ ] **Step 2: Run the new tests and observe failure**

```bash
cd /Users/jcords-macmini/projects-local/a2a-cli-registry
.venv/bin/python -m pytest tests/test_capability_extractor.py tests/test_backfill_capabilities.py -q -k 'typed_output or generate_pdf_reportlab or consumers_unsaved or output_normalization'
```

Expected FAIL: `'file:pdf'` (or another `file:` token) is absent from coarse output lists; the normalization test also reports the missing `with_typed_outputs` import. Negative consumer cases should already pass.

- [ ] **Step 3: Implement additive typed extraction and normalization**

Add `from pathlib import PurePath` beside the extractor's existing imports, then insert these complete helpers before `extract_outputs`:

```python
def _scope_nodes(root: ast.AST):
    """Walk one lexical scope without borrowing a writer from another."""
    yield root
    for child in ast.iter_child_nodes(root):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from _scope_nodes(child)


def _literal_path(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ('Path', 'PurePath') and len(node.args) == 1:
            return _literal_path(node.args[0])
    return None


def _argument(call: ast.Call, index: int, name: str) -> ast.AST | None:
    if len(call.args) > index:
        return call.args[index]
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def typed_file_outputs(source: str) -> list[str]:
    if not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        destination = None
        if isinstance(node.func, ast.Name) and node.func.id == 'open':
            mode = _literal_path(_argument(node, 1, 'mode')) or 'r'
            if any(flag in mode for flag in ('w', 'a', 'x')):
                destination = _argument(node, 0, 'file')
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in ('write_text', 'write_bytes'):
                destination = node.func.value
            elif node.func.attr in ('save', 'savefig'):
                destination = _argument(node, 0, 'fname' if node.func.attr == 'savefig' else 'filename')
        path = _literal_path(destination)
        if path:
            extension = PurePath(path).suffix.removeprefix('.').lower()
            if re.fullmatch(r'[a-z0-9]{1,12}', extension):
                found.add(f'file:{extension}')

    module_nodes = list(_scope_nodes(tree))
    scopes = [tree] + [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        nodes = list(_scope_nodes(scope))
        constructors = set()
        for node in module_nodes + nodes:
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                name = alias.asname or alias.name
                if node.module == 'reportlab.pdfgen' and alias.name == 'canvas':
                    constructors.add(f'{name}.Canvas')
                elif node.module == 'reportlab.pdfgen.canvas' and alias.name == 'Canvas':
                    constructors.add(name)
        canvases = set()
        for node in nodes:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if ast.unparse(node.value.func) in constructors:
                    canvases.update(t.id for t in node.targets if isinstance(t, ast.Name))
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == 'save' and isinstance(n.func.value, ast.Name)
               and n.func.value.id in canvases for n in nodes):
            found.add('file:pdf')
    return sorted(found)


def with_typed_outputs(capability: dict | None, source: str) -> dict | None:
    if capability is None:
        return None
    outputs = list(dict.fromkeys(capability.get('output_types', []) + typed_file_outputs(source)))
    return {**capability, 'output_types': outputs}
```

In `extract_outputs`, immediately before `is_json_stdout = False`, insert:

```python
    typed = typed_file_outputs(source)
    if typed:
        outputs.append('path')
        outputs.extend(typed)
```

The existing final stable deduplication produces `['path', 'file:pdf']` for the verified ReportLab source and preserves the existing coarse-port tests. `open(..., mode='x')` and `write_bytes` gain `path` through the same additive block when their literal extension is known. This is deliberately a small source recognizer, not arbitrary Python data-flow analysis; unknown dynamic formats stay coarse.

In `run_pipeline`, insert this complete statement immediately after the fallback block (at the indentation of `proposals.append`, so non-Python `None` stays `None`):

```python
        capability = capability_extractor.with_typed_outputs(capability, source)
```

Immediately after `if repaired is None: continue` and before the repair's sanity recheck, insert:

```python
        repaired['capability'] = capability_extractor.with_typed_outputs(
            repaired['capability'], source
        )
```

Both normalized proposals are judged before adoption. Leave the LLM prompts coarse; deterministic source evidence supplies typed ports without asking the model to guess extensions. `--from-proposals` continues to commit exactly reviewed data; use newly generated proposals for future regeneration. Task 5 handles the already-committed fleet without replaying the old phase-0 artifact.

- [ ] **Step 4: Run extractor, pipeline and unchanged catalog regression tests**

```bash
.venv/bin/python -m pytest tests/test_capability_extractor.py tests/test_backfill_capabilities.py tests/test_catalog.py tests/test_vocabulary.py -q
```

Expected PASS for non-skipped cases, including all four fallback/repair combinations. No change to `search_clis`, vocabulary admission, or description generation is needed.

- [ ] **Step 5: Commit the typed-output regeneration change**

```bash
git add -- tools/capability_extractor.py tools/backfill_capabilities.py tests/test_capability_extractor.py tests/test_backfill_capabilities.py
git commit -m "feat: retain typed producer outputs during capability regeneration" -- tools/capability_extractor.py tools/backfill_capabilities.py tests/test_capability_extractor.py tests/test_backfill_capabilities.py
```

---

## Chunk 3: Apply bounded hygiene to the live registry and prove the ACs

### Task 5: Regenerate existing output ports and resolve the 37 placeholders (27 disabled, 10 described)

Implements spec §9 and §16 AC-01/AC-02, and verifies AC-03 on the migrated live schema. Spec §4 is binding: no live CLI, capability, edge, source file, or legacy column is deleted. Disabling a missing-source row removes it from the enabled population while retaining its description and all evidence. Existing files with a placeholder description are live tools, not candidates for disabling: each gets a reviewed description from a committed JSON file, written with `description_provenance='manual'` so no writer overwrites it. Any placeholder with an existing source and no reviewed description is unresolved and blocks application. A count change from the measured 27 missing / 10 live is investigated before application.

This task deliberately does not run `populate` (which has its own removal semantics), invoke source CLIs, call an LLM, replay the phase-0 reviewed artifact, change manual capabilities, or recompute the graph. The new command shares the registry lock and SQLite transaction discipline. It is also the explicit live migration entrypoint, with a SQLite backup before the first schema/data change.

**Files:**
- Create: `tools/registry_hygiene.py`
- Create: `tests/test_registry_hygiene.py`
- Create: `data/hygiene/caploop-04-descriptions.json` (Step 7b; reviewed one-sentence descriptions for the 10 live placeholders)
- Test: `tests/test_registry_hygiene.py`
- Runtime Modify: `/Users/jcords-macmini/.hermes/cli-registry.db` (verified target; never committed)
- Runtime Create: `<db-name>.hygiene-<unique>.bak` beside the selected DB (never committed)
- Read: `core/catalog/queries.py:71-85`, `core/store/db.py:44-51`, Task 1 migration and Task 4 extractor

- [ ] **Step 1: Write the failing hygiene and catalog acceptance tests**

Create the complete `tests/test_registry_hygiene.py`:

```python
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlmodel import Session

from core.catalog.queries import search_clis
from core.models import Cli, Capability
from core.store.db import init_db
from tools import registry_hygiene as hygiene


PDF_SOURCE = '''
def render(output_path):
    from reportlab.pdfgen import canvas as rl_canvas
    c = rl_canvas.Canvas(str(output_path))
    c.save()
'''


def make_db(tmp_path, *, readable_unknown=False):
    path = tmp_path / 'registry.db'
    producer = tmp_path / 'producer.py'
    producer.write_text(PDF_SOURCE)
    consumer = tmp_path / 'consumer.py'
    consumer.write_text('print(open("input.pdf").read())')
    engine = init_db(str(path))
    with Session(engine) as session:
        session.add(Cli(slug='generate_pdf', lang='python', path=str(producer),
                        description='Renders a document.', description_provenance='llm'))
        session.add(Capability(cli_slug='generate_pdf', output_types='path',
                               intent_tags='generate', provenance='static'))
        session.add(Cli(slug='manual', lang='python', path=str(producer),
                        description='Curated producer.', description_provenance='manual'))
        session.add(Capability(cli_slug='manual', output_types='curated-output', provenance='manual'))
        session.add(Cli(slug='consumer', lang='python', path=str(consumer), description='Reads a document.'))
        session.add(Capability(cli_slug='consumer', output_types='text', provenance='static'))
        for i in range(37):
            slug = f'gone-{i:02d}'
            session.add(Cli(slug=slug, lang='python', path=str(tmp_path / f'{slug}.py'),
                            description=f'unknown purpose ({slug})', description_provenance='llm'))
            session.add(Capability(cli_slug=slug, output_types='', provenance='llm'))
        session.add(Cli(slug='already-disabled', lang='python', enabled=False,
                        path=str(tmp_path / 'disabled.py'), description='unknown purpose (already-disabled)'))
        if readable_unknown:
            session.add(Cli(slug='unresolved', lang='python', path=str(producer),
                            description='unknown purpose (unresolved)'))
        session.commit()
    engine.dispose()
    return str(path)


def rows(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        return (
            con.execute('SELECT * FROM cli ORDER BY slug').fetchall(),
            con.execute('SELECT * FROM capability ORDER BY id').fetchall(),
        )


def test_preview_is_read_only_and_targets_only_missing_unknowns(tmp_path):
    path = make_db(tmp_path)
    before = rows(path)
    report = hygiene.inspect_db(path)
    assert len(report['disable']) == 37
    assert report['unresolved'] == []
    assert [r['slug'] for r in report['outputs']] == ['generate_pdf']
    assert report['outputs'][0]['after'] == 'path,file:pdf'
    assert rows(path) == before
    assert list(tmp_path.glob('*.bak')) == []
    assert not Path(path + '.lock').exists()


def test_apply_satisfies_ac01_ac02_without_losing_rows(tmp_path):
    path = make_db(tmp_path)
    before = rows(path)
    report = hygiene.apply_hygiene(path, expected_missing=37)
    assert rows(report['backup']) == before
    after = rows(path)
    assert len(after[0]) == len(before[0])
    assert len(after[1]) == len(before[1])
    with closing(sqlite3.connect(path)) as con:
        assert con.execute("SELECT COUNT(*) FROM cli WHERE enabled=1 AND lower(trim(description)) LIKE 'unknown purpose%'").fetchone()[0] == 0
        assert con.execute("SELECT description, description_provenance, enabled FROM cli WHERE slug='gone-00'").fetchone() == ('unknown purpose (gone-00)', 'llm', 0)
        assert con.execute("SELECT output_types, provenance FROM capability WHERE cli_slug='manual'").fetchone() == ('curated-output', 'manual')
        assert con.execute("SELECT output_types FROM capability WHERE cli_slug='consumer'").fetchone() == ('text',)
    engine = init_db(path)
    try:
        with Session(engine) as session:
            assert [r['slug'] for r in search_clis(session, 'file:pdf')] == ['generate_pdf']
    finally:
        engine.dispose()
    assert hygiene.inspect_db(path)['outputs'] == []
    repeat = hygiene.apply_hygiene(path, expected_missing=0)
    assert repeat['disable'] == [] and repeat['outputs'] == [] and repeat['backup'] is None
    assert rows(path) == after


@pytest.mark.parametrize('readable_unknown', [False, True])
def test_refuses_wrong_count_or_readable_placeholder_before_any_write(tmp_path, readable_unknown):
    path = make_db(tmp_path, readable_unknown=readable_unknown)
    before = rows(path)
    expected = 37 if readable_unknown else 36
    with pytest.raises(ValueError, match='unresolved|expected'):
        hygiene.apply_hygiene(path, expected_missing=expected)
    assert rows(path) == before
    assert list(tmp_path.glob('*.bak')) == []


def test_reviewed_descriptions_resolve_live_placeholders(tmp_path):
    path = make_db(tmp_path, readable_unknown=True)
    report = hygiene.apply_hygiene(path, expected_missing=37,
                                   descriptions={'unresolved': 'Renders a document to PDF.'})
    assert report['described'] == ['unresolved']
    with closing(sqlite3.connect(path)) as con:
        assert con.execute(
            "SELECT description, description_provenance, enabled FROM cli WHERE slug='unresolved'"
        ).fetchone() == ('Renders a document to PDF.', 'manual', 1)
        assert con.execute("SELECT COUNT(*) FROM cli WHERE enabled=1 AND lower(trim(description)) LIKE 'unknown purpose%'").fetchone()[0] == 0


@pytest.mark.parametrize('descriptions', [{'generate_pdf': 'Not a placeholder.'}, {'unresolved': '   '}])
def test_descriptions_must_target_live_placeholders_and_be_nonempty(tmp_path, descriptions):
    path = make_db(tmp_path, readable_unknown=True)
    before = rows(path)
    with pytest.raises(ValueError, match='not live placeholders|unresolved'):
        hygiene.apply_hygiene(path, expected_missing=37, descriptions=descriptions)
    assert rows(path) == before
    assert list(tmp_path.glob('*.bak')) == []


def test_permission_error_does_not_mean_source_is_missing(tmp_path, monkeypatch):
    path = make_db(tmp_path)
    real_stat = Path.stat

    def denied(self, *args, **kwargs):
        if self.name == 'gone-00.py':
            raise PermissionError('fixture denial')
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', denied)
    report = hygiene.inspect_db(path)
    assert 'gone-00' not in report['disable']
    assert 'gone-00' in report['unresolved']
    with pytest.raises(ValueError, match='unresolved'):
        hygiene.apply_hygiene(path, expected_missing=37)


def test_backup_failure_prevents_any_mutation(tmp_path, monkeypatch):
    path = make_db(tmp_path)
    before = rows(path)

    def fail(path):
        raise OSError('disk full')

    monkeypatch.setattr(hygiene, '_backup', fail)
    with pytest.raises(OSError, match='disk full'):
        hygiene.apply_hygiene(path, expected_missing=37)
    assert rows(path) == before


def test_sql_failure_rolls_back_output_and_enabled_changes(tmp_path):
    path = make_db(tmp_path)
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TRIGGER reject_disable BEFORE UPDATE OF enabled ON cli
            WHEN NEW.enabled=0 BEGIN SELECT RAISE(ABORT, 'fixture rejection'); END""")
    before = rows(path)
    with pytest.raises(sqlite3.IntegrityError, match='fixture rejection'):
        hygiene.apply_hygiene(path, expected_missing=37)
    assert rows(path) == before


def test_missing_database_is_not_created(tmp_path):
    path = str(tmp_path / 'absent.db')
    with pytest.raises(FileNotFoundError):
        hygiene.inspect_db(path)
    assert not Path(path).exists()
```

- [ ] **Step 2: Run the new tests and observe failure**

```bash
.venv/bin/python -m pytest tests/test_registry_hygiene.py -q
```

Expected FAIL during collection: `ImportError: cannot import name 'registry_hygiene' from 'tools'`. These tests will establish actual catalog visibility from regenerated ports, not a hard-coded typed fixture alone.

- [ ] **Step 3: Implement the complete deterministic hygiene command**

Create `tools/registry_hygiene.py`:

```python
"""US-CAPLOOP-04: additive typed outputs and reversible missing-source hygiene.

Run from the registry root with python -m tools.registry_hygiene.
Preview is read-only. Application requires an explicit missing-source count.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from core.store.db import with_file_lock
from core.store.migrations import migrate_description_provenance
from tools.capability_extractor import typed_file_outputs


def _connect(db_path: str, *, readonly: bool = True) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    mode = 'ro' if readonly else 'rw'
    con = sqlite3.connect(path.as_uri() + f'?mode={mode}', uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def _inspect(con: sqlite3.Connection) -> dict:
    rows = con.execute(
        'SELECT slug, lang, path, description FROM cli WHERE enabled=1 ORDER BY slug'
    ).fetchall()
    report = {'enabled': len(rows), 'disable': [], 'unresolved': [], 'outputs': []}
    for row in rows:
        slug = row['slug']
        unknown = (row['description'] or '').strip().lower().startswith('unknown purpose')
        path = Path(row['path']).expanduser() if row['path'] else None
        missing = False
        regular = False
        try:
            regular = path is not None and stat.S_ISREG(path.stat().st_mode)
        except FileNotFoundError:
            missing = True
        except OSError:
            regular = False
        if unknown:
            report['disable' if missing else 'unresolved'].append(slug)
            continue
        if row['lang'] != 'python' or not regular:
            continue
        try:
            source = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        typed = typed_file_outputs(source)
        if not typed:
            continue
        caps = con.execute(
            'SELECT id, output_types, provenance FROM capability WHERE cli_slug=? ORDER BY id',
            (slug,),
        ).fetchall()
        for cap in caps:
            if cap['provenance'] not in (None, 'static', 'llm'):
                continue
            before = cap['output_types'] or ''
            ports = [p for p in before.split(',') if p]
            additions = [p for p in typed if p not in ports]
            if additions:
                report['outputs'].append({
                    'id': cap['id'], 'slug': slug, 'before': before,
                    'after': ','.join(ports + additions),
                })
    return report


def inspect_db(db_path: str) -> dict:
    with closing(_connect(db_path)) as con:
        return _inspect(con)


def _backup(db_path: str) -> str:
    path = Path(db_path).expanduser().resolve()
    fd, name = tempfile.mkstemp(prefix=path.name + '.hygiene-', suffix='.bak', dir=path.parent)
    os.close(fd)
    with closing(_connect(str(path))) as source:
        with closing(sqlite3.connect(name)) as target:
            source.backup(target)
    return name


def apply_hygiene(db_path: str, *, expected_missing: int,
                  descriptions: dict[str, str] | None = None) -> dict:
    """descriptions: reviewed text for placeholder rows whose source still exists."""
    descriptions = {s: (t or '').strip() for s, t in (descriptions or {}).items()}
    path = str(Path(db_path).expanduser().resolve())
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    with with_file_lock(path + '.lock'):
        with closing(_connect(path, readonly=False)) as con:
            try:
                # Block other SQLite writers, including Governance's upsert.
                # The backup uses a separate read connection before mutation.
                con.execute('BEGIN IMMEDIATE')
                report = _inspect(con)
                stray = sorted(set(descriptions) - set(report['unresolved']))
                if stray:
                    raise ValueError(f"descriptions for rows that are not live placeholders: {stray}")
                blocked = [s for s in report['unresolved'] if not descriptions.get(s)]
                if blocked:
                    raise ValueError(f"unresolved unknown purpose rows: {blocked}")
                if len(report['disable']) != expected_missing:
                    raise ValueError(f"expected {expected_missing} missing rows, found {len(report['disable'])}")
                report['described'] = sorted(descriptions)
                needs_migration = 'description_provenance' not in {
                    r[1] for r in con.execute('PRAGMA table_info(cli)')
                }
                if (not needs_migration and not report['outputs']
                        and not report['disable'] and not descriptions):
                    con.rollback()
                    return {**report, 'backup': None}
                backup = _backup(path)
                migrate_description_provenance(con)
                for change in report['outputs']:
                    result = con.execute("""
                        UPDATE capability SET output_types=?
                        WHERE id=? AND output_types=?
                          AND (provenance IS NULL OR provenance IN ('static','llm'))
                    """, (change['after'], change['id'], change['before']))
                    if result.rowcount != 1:
                        raise RuntimeError(f"capability changed during hygiene: {change['id']}")
                for slug in report['disable']:
                    con.execute('UPDATE cli SET enabled=0 WHERE slug=?', (slug,))
                for slug, text in descriptions.items():
                    result = con.execute("""
                        UPDATE cli SET description=?, description_provenance='manual'
                        WHERE slug=? AND enabled=1
                          AND lower(trim(description)) LIKE 'unknown purpose%'
                    """, (text, slug))
                    if result.rowcount != 1:
                        raise RuntimeError(f"placeholder changed during hygiene: {slug}")
                remaining = con.execute("""
                    SELECT COUNT(*) FROM cli WHERE enabled=1
                      AND lower(trim(description)) LIKE 'unknown purpose%'
                """).fetchone()[0]
                if remaining:
                    raise RuntimeError(f'{remaining} enabled unknown purpose rows remain')
                con.commit()
                return {**report, 'backup': backup}
            except Exception:
                con.rollback()
                raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-missing', type=int)
    parser.add_argument('--descriptions', help='JSON object {slug: reviewed description}')
    args = parser.parse_args(argv)
    if args.apply and (args.expect_missing is None or args.expect_missing < 0):
        parser.error('--apply requires --expect-missing with a nonnegative count')
    descriptions = (json.loads(Path(args.descriptions).read_text(encoding='utf-8'))
                    if args.descriptions else None)
    result = (apply_hygiene(args.db, expected_missing=args.expect_missing,
                            descriptions=descriptions)
              if args.apply else inspect_db(args.db))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
```

`BEGIN IMMEDIATE` spans inspection, SQLite backup, migration and data writes. The separate backup connection reads the committed pre-mutation snapshot while other writers are blocked. This avoids copying only a DB file while committed pages may still be in WAL. A backup error rolls back before migration; a later write error rolls back both migration and data. Dry-run uses `mode=ro`, creates no lock or artifact, and does not call `init_db`. No new model import is introduced into `tools`, preserving the existing raw-SQL drift contract.

- [ ] **Step 4: Run hygiene acceptance and all touched-area regression tests**

```bash
.venv/bin/python -m pytest tests/test_registry_hygiene.py tests/test_description_provenance_migration.py tests/test_fixed_by_migration.py tests/test_populate.py tests/test_backfill_capabilities.py tests/test_capability_extractor.py tests/test_description_regenerator.py tests/test_catalog.py tests/test_vocabulary.py -q
```

Expected PASS for every non-skipped test. Specifically, the acceptance fixture goes from 37 enabled placeholders to zero, keeps both row counts, backs up the exact original rows, leaves manual output unchanged, finds `generate_pdf` through the real `search_clis`, and produces no further work on repetition. A failing test is fixed before live application; do not weaken assertions or the calibrated backfill gates.

- [ ] **Step 5: Commit the tested hygiene command in the registry repo**

```bash
git add -- tools/registry_hygiene.py tests/test_registry_hygiene.py
git commit -m "feat: apply reversible capability-loop registry hygiene" -- tools/registry_hygiene.py tests/test_registry_hygiene.py
```

The remaining steps are operational application of that tested code, not another implementation cycle. They do not create a DB commit in Git.

- [ ] **Step 6: Recheck the live target and counts read-only**

```bash
sqlite3 -readonly /Users/jcords-macmini/.hermes/cli-registry.db <<'SQL'
SELECT COUNT(*) AS total_rows, SUM(enabled) AS enabled_rows,
       SUM(enabled=1 AND lower(trim(description)) LIKE 'unknown purpose%') AS unknown_enabled
FROM cli;
SELECT c.slug, c.path, k.output_types, k.provenance
FROM cli c LEFT JOIN capability k ON k.cli_slug=c.slug
WHERE c.slug='generate_pdf';
PRAGMA table_info(cli);
PRAGMA table_info(capability);
SQL
```

Expected baseline if no other session has applied the work: `636|612|37`; `generate_pdf` still has coarse `path`. A pre-existing parent field or changed counts is evidence to inspect, not a reason to drop/recreate columns or forcibly reset data. Preserve other sessions' work. Confirm Task 3 has landed in Governance before continuing, so routine registrations cannot undo the migration's descriptions.

- [ ] **Step 7: Preview the exact live hygiene actions**

```bash
.venv/bin/python -m tools.registry_hygiene --db /Users/jcords-macmini/.hermes/cli-registry.db
```

Expected: `disable` lists 27 slugs, `unresolved` lists the 10 live tools named in the Scope correction, and `outputs` includes `generate_pdf` changing `path` to `path,file:pdf`. Other source-evidenced non-manual producers may receive additive typed outputs. Review the printed records. If the measured counts have changed, reconcile them before choosing a new explicit expected count.

- [ ] **Step 7b: Write and commit the reviewed descriptions for the 10 live placeholders**

For each slug in `unresolved`, read its source at the registered `path` (for `causa` the path is a directory: read its README and entry point; `oc` and `prefab` are installed binaries: read `--help` output only, never run a subcommand). Write one sentence each, in the registry's description style (verb-first, what it does, no marketing), to `data/hygiene/caploop-04-descriptions.json` as `{"<slug>": "<sentence>", ...}` with exactly the 10 unresolved slugs as keys. Do not guess: a tool whose purpose cannot be established from its source or help text stays out of the file, and application then refuses with that slug named — report it in the handoff instead of inventing prose.

```bash
python3 -c "import json;d=json.load(open('data/hygiene/caploop-04-descriptions.json'));print(len(d), sorted(d))"
git add -- data/hygiene/caploop-04-descriptions.json
git commit -m "data: reviewed descriptions for the 10 live unknown-purpose CLIs (US-CAPLOOP-04)" -- data/hygiene/caploop-04-descriptions.json
```

Expected: `10` and the 10 slugs.

- [ ] **Step 8: Apply the reviewed deterministic actions with backup**

```bash
.venv/bin/python -m tools.registry_hygiene --db /Users/jcords-macmini/.hermes/cli-registry.db --apply --expect-missing 27 --descriptions data/hygiene/caploop-04-descriptions.json
```

Expected: a printed backup path, the same 27 disabled slugs, `described` listing the 10, and typed additions. The tool rescans inside the transaction, checks the expected count, the unresolved list against the reviewed descriptions, then backs up before mutation. With the measured baseline, enabled rows become 585 (612 − 27); total CLI rows remain 636 and capability rows remain 614. The 10 described rows carry `description_provenance='manual'`. Do not stage the live DB, backup, or lock file.

- [ ] **Step 9: Verify all three ACs against the live database through read-only connections**

Run this complete acceptance probe from the registry root. It uses `search_clis` itself and does not call the mutating `init_db`:

```bash
.venv/bin/python - <<'PY'
import sqlite3
from contextlib import closing
from pathlib import Path
from sqlmodel import Session, create_engine
from core.catalog.queries import search_clis

path = Path('/Users/jcords-macmini/.hermes/cli-registry.db')
uri = path.as_uri() + '?mode=ro'
with closing(sqlite3.connect(uri, uri=True)) as con:
    assert 'description_provenance' in {r[1] for r in con.execute('PRAGMA table_info(cli)')}
    total, enabled, unknown = con.execute("""
        SELECT COUNT(*), SUM(enabled),
               SUM(enabled=1 AND lower(trim(description)) LIKE 'unknown purpose%') FROM cli
    """).fetchone()
    assert unknown == 0, (total, enabled, unknown)
    # No cleanup deletes: compare these with Step 6 if concurrent registrations changed the baseline.
    assert total >= 636, total
    assert con.execute('SELECT COUNT(*) FROM capability').fetchone()[0] >= 614
    lost_manual = con.execute("""
        SELECT DISTINCT k.cli_slug FROM capability k JOIN cli c ON c.slug=k.cli_slug
        WHERE k.description_provenance='manual'
          AND c.description_provenance IS NOT 'manual'
    """).fetchall()
    assert lost_manual == [], lost_manual
engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(uri, uri=True))
try:
    with Session(engine) as session:
        matches = search_clis(session, 'file:pdf')
        assert 'generate_pdf' in {r['slug'] for r in matches}, matches
finally:
    engine.dispose()
print(f'AC-01 PASS; AC-02 PASS ({unknown} enabled unknowns); AC-03 parent migration PASS; rows={total}, enabled={enabled}')
PY
```

AC-03's re-registration half is established by Task 3's subprocess tests against temporary legacy and migrated DBs; do not re-register a live CLI merely to prove the guard and alter its metadata. The inert legacy marker is read here only to confirm none of the originally manual descriptions lost protection. If the legacy column never existed (a new deployment), use Task 1's fresh-schema tests instead of this legacy-data cross-check.

- [ ] **Step 10: Verify repeat hygiene is a read-only no-op preview**

```bash
.venv/bin/python -m tools.registry_hygiene --db /Users/jcords-macmini/.hermes/cli-registry.db
```

Expected: `disable=[]`, `unresolved=[]`, `outputs=[]`. Record the actual test results, baseline/post-application counts and printed backup path in the implementation handoff. Do not edit DECISIONS.md or commit operational DB files as part of this plan. No service-manager operation is required to prove these direct-DB ACs; deployment of a long-running registry process follows that project's normal deployment procedure.

## AC coverage

| AC text (spec §16, US-CAPLOOP-04) | Task/Step |
|---|---|
| AC-01: `search_clis("file:pdf")` lists `generate_pdf`. | Task 4 Steps 1–4 generate and retain typed output; Task 5 Steps 1–4 test the actual catalog query after hygiene; Task 5 Steps 7–9 apply and prove the live result. |
| AC-02: `unknown purpose` rows are 0 among enabled CLIs (the 37 whose source files are gone are resolved). | Task 5 Steps 1–4 test missing-only disabling, reviewed descriptions for live placeholders, row retention, refusal and idempotency; Steps 6–10 check the measured 27 missing + 10 live, write the reviewed descriptions (7b), apply and verify zero enabled placeholders. |
| AC-03: `description_provenance` lives on `cli`, and the `register_cli.py:181` re-register rewrite is guarded by it. | Task 1 Steps 1–4 test/migrate parent ownership; Task 2 Steps 1–4 preserve independent registry writer guards; Task 3 Steps 1–4 guard the real Governance upsert; Task 5 Steps 8–9 migrate and verify the live parent markers. |

## Decisions this plan makes

1. **How to resolve missing-source placeholders?** Disable only enabled placeholder rows whose nonempty source path raises `FileNotFoundError`; alternatives were deletion, invented descriptions, or source restoration. Disabling satisfies the enabled-row AC, preserves evidence under §4, and is reversible.
1a. **What about placeholders whose source still exists?** (Added in Claude review: the spec's "37 whose source files are gone" measures as 27 gone + 10 live.) Give each live tool a reviewed one-sentence description from a committed JSON file, written as `manual`; alternatives were disabling them too (hides working tools such as `causa` and `invoice-fetcher`) or an LLM regeneration run (not reviewed, and Q7 did not authorize one). A slug whose purpose cannot be read from its source stays unresolved and blocks application.
2. **What to do with the old persisted column?** Keep it inert in legacy DBs, remove it from the active capability model, and create it nowhere new; alternatives were dropping it or dual-writing. Additive migration respects §4 and avoids competing ownership authorities.
3. **How to resolve multiple legacy markers and migration repetition?** On first parent-column creation choose `manual`, then `llm`, then `static`, then lexically ordered other non-NULL markers; an existing parent column always wins, including NULL. Alternatives were arbitrary first-row selection, rejecting all conflicts, or repeated NULL backfills. Manual-first prevents loss of curation, deterministic selection handles multi-row CLIs, and one-time copying prevents stale legacy values from resurrecting cleared ownership.
4. **Where and how to migrate?** Use a shared transaction-level migration, invoked on the engine connection before table creation and by raw-SQL tools; explicit hygiene backs up before calling it on the live DB. Alternatives were ORM-only changes, a startup migration using a second connection, or separate uncoordinated ALTER/copy commits. The chosen approach supports drifted and in-memory DBs and makes schema-plus-copy atomic.
5. **Which re-registration owners are protected?** Preserve `manual`, `static` and `llm` parent markers, including against explicit `--description`; unowned new/existing rows retain their prior behavior. Alternatives were manual-only protection, marking every registration manual, or adding a force flag. The chosen behavior matches discovery's established ownership policy and introduces no unrequested override surface.
6. **How to handle a Governance/registry deployment gap?** Governance reads legacy child description markers only when the parent column is absent; alternatives were requiring a perfectly synchronized rollout or allowing a missing-column registration skip. Read-only compatibility protects curation on either rollout order without making Governance a schema owner.
7. **How far to extend typed inference?** Add literal writer extensions plus saved ReportLab canvases, retain coarse outputs, and normalize after fallback/repair before judging; alternatives were slug/description guessing, matcher special cases, changing LLM vocabulary alone, or general interprocedural analysis. This covers the verified producer and general literal destinations with deterministic evidence while leaving unknown dynamic formats coarse.
8. **How to update the existing fleet?** Use the same source extractor in a deterministic, previewable, transactional hygiene command, preserving manual capabilities and all non-output fields; alternatives were rerunning the whole LLM backfill, replaying the old reviewed artifact, or hard-coding `generate_pdf`. This limits writes to the AC-required facts and avoids treating Q7's earlier approval as approval of new LLM proposals.
9. **What backup and concurrency boundary to use?** Use the existing sidecar lock plus `BEGIN IMMEDIATE`, take a SQLite backup through a separate read connection before any mutation, and require the observed missing-row count; alternatives were copying the DB file, scanning outside the write transaction, or silently accepting population changes. This includes committed WAL data and prevents registrations from interleaving with migration/application.
10. **When is the live DB first backed up?** (Added in Claude review.) Task 1 Step 0, before the auto-migrating `init_db` lands, because any registry command run after Task 1 migrates the live DB before Task 5's backup exists; alternative was relying on Task 5's backup alone, which would postdate the schema change.
