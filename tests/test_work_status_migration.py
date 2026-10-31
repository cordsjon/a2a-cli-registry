import sqlite3

from sqlmodel import select

from core.models import Cli
from core.store.db import get_session, init_db
from core.store.migrations import ensure_work_status_columns


def _legacy_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cli (slug TEXT PRIMARY KEY, health_status TEXT)")
    con.execute("INSERT INTO cli (slug, health_status) VALUES ('a','healthy')")
    con.commit()
    con.close()


def test_migration_adds_both_columns_once(tmp_path):
    db = str(tmp_path / "registry.db")
    _legacy_db(db)
    ensure_work_status_columns(db)
    ensure_work_status_columns(db)  # second call must not raise "duplicate column"
    con = sqlite3.connect(db)
    cols = [row[1] for row in con.execute("PRAGMA table_info(cli)")]
    row = con.execute("SELECT work_status, work_checked_at FROM cli").fetchone()
    con.close()
    assert cols.count("work_status") == 1
    assert cols.count("work_checked_at") == 1
    assert row == ("unknown", None)


def test_migration_is_a_noop_without_the_table(tmp_path):
    db = str(tmp_path / "registry.db")
    ensure_work_status_columns(db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM sqlite_master").fetchall() == []
    con.close()


def test_init_db_makes_a_pre_existing_db_readable(tmp_path):
    """The wiring, not the part: a model field on an old DB breaks every
    select(Cli), so the column has to exist before any command can read."""
    db = str(tmp_path / "registry.db")
    engine = init_db(db)
    with get_session(engine) as s:
        s.add(Cli(slug="old", lang="python"))
        s.commit()
    engine.dispose()
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE cli DROP COLUMN work_status")
    con.execute("ALTER TABLE cli DROP COLUMN work_checked_at")
    con.commit()
    con.close()

    engine = init_db(db)
    with get_session(engine) as s:
        assert s.exec(select(Cli)).one().work_status == "unknown"
    engine.dispose()
