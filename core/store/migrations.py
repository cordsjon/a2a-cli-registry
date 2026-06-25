"""One-shot, existence-guarded schema migrations for the SQLite registry.

create_all() (core/store/db.py) creates missing TABLES but never ALTERs an
existing table to add a COLUMN. A model field added to a persisted table is
therefore invisible to an existing DB file until an explicit ALTER runs. These
functions are idempotent: safe to call on every command invocation."""
import sqlite3


def _table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    return row is not None


def _column_exists(con, table: str, column: str) -> bool:
    return any(r[1] == column for r in con.execute(f"PRAGMA table_info({table})"))


def ensure_fixed_by_column(db_path: str) -> None:
    """Add cli.fixed_by if the table exists and the column does not. No-op
    otherwise. Idempotent — a second call sees the column and returns."""
    con = sqlite3.connect(db_path)
    try:
        if _table_exists(con, "cli") and not _column_exists(con, "cli", "fixed_by"):
            con.execute("ALTER TABLE cli ADD COLUMN fixed_by TEXT")
            con.commit()
    finally:
        con.close()
