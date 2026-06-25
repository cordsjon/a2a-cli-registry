import sqlite3
from core.store.migrations import ensure_fixed_by_column


def _make_legacy_db(path):
    # A 'cli' table WITHOUT fixed_by — simulates the pre-migration production DB.
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cli (slug TEXT PRIMARY KEY, health_status TEXT)")
    con.execute("INSERT INTO cli (slug, health_status) VALUES ('a','unhealthy')")
    con.commit()
    con.close()


def test_migration_adds_missing_column(tmp_path):
    db = str(tmp_path / "registry.db")
    _make_legacy_db(db)
    ensure_fixed_by_column(db)
    con = sqlite3.connect(db)
    cols = {row[1] for row in con.execute("PRAGMA table_info(cli)")}
    con.close()
    assert "fixed_by" in cols


def test_migration_is_idempotent(tmp_path):
    db = str(tmp_path / "registry.db")
    _make_legacy_db(db)
    ensure_fixed_by_column(db)
    ensure_fixed_by_column(db)  # second call must not raise "duplicate column"
    con = sqlite3.connect(db)
    cols = [row[1] for row in con.execute("PRAGMA table_info(cli)")]
    con.close()
    assert cols.count("fixed_by") == 1


def test_migration_preserves_existing_rows(tmp_path):
    db = str(tmp_path / "registry.db")
    _make_legacy_db(db)
    ensure_fixed_by_column(db)
    con = sqlite3.connect(db)
    row = con.execute("SELECT slug, health_status, fixed_by FROM cli WHERE slug='a'").fetchone()
    con.close()
    assert row == ("a", "unhealthy", None)


def test_migration_noop_when_table_absent(tmp_path):
    # A DB with no 'cli' table at all must not raise (create_all handles creation).
    db = str(tmp_path / "empty.db")
    sqlite3.connect(db).close()
    ensure_fixed_by_column(db)  # must be a silent no-op


def test_migration_tolerates_lost_toctou_race(tmp_path, monkeypatch):
    # Two concurrent callers can both pass the _column_exists check, then the
    # second ALTER raises "duplicate column name". Simulate the loser of that
    # race by forcing _column_exists to report absent even though the column
    # is already there — ensure_fixed_by_column must swallow the duplicate-
    # column OperationalError, not crash the command.
    import core.store.migrations as mig
    db = str(tmp_path / "registry.db")
    _make_legacy_db(db)
    ensure_fixed_by_column(db)  # column now genuinely present
    monkeypatch.setattr(mig, "_column_exists", lambda con, table, column: False)
    # second call: check lies "absent" -> ALTER runs -> duplicate column -> must NOT raise
    ensure_fixed_by_column(db)
    con = sqlite3.connect(db)
    cols = [row[1] for row in con.execute("PRAGMA table_info(cli)")]
    con.close()
    assert cols.count("fixed_by") == 1
