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


def test_migrated_db_opens_while_another_writer_holds_the_lock(tmp_path):
    # Final review: init_db took BEGIN IMMEDIATE on every open, so a read-only
    # command (serve, probe, okf-produce, remediate) failed with "database is
    # locked" whenever populate or backfill held the write lock.
    path = tmp_path / 'registry.db'
    init_db(str(path)).dispose()
    holder = sqlite3.connect(path)
    holder.execute('BEGIN IMMEDIATE')
    try:
        engine = init_db(str(path))
        engine.dispose()
    finally:
        holder.rollback()
        holder.close()
