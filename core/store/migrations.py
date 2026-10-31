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


_WORK_STATUS_COLUMNS = {
    "work_status": "TEXT NOT NULL DEFAULT 'unknown'",
    "work_checked_at": "REAL",
}


def ensure_work_status_columns(db_path: str) -> None:
    """Add cli.work_status and cli.work_checked_at where missing. Idempotent.
    Runs from init_db: every select(Cli) names these columns, so unlike fixed_by
    no command can read an existing DB until they exist."""
    con = sqlite3.connect(db_path)
    try:
        if not _table_exists(con, "cli"):
            return
        for column, declaration in _WORK_STATUS_COLUMNS.items():
            if _column_exists(con, "cli", column):
                continue
            try:
                con.execute(f"ALTER TABLE cli ADD COLUMN {column} {declaration}")
                con.commit()
            except sqlite3.OperationalError as exc:
                # A concurrent caller won the check-then-ALTER race; see below.
                if "duplicate column" not in str(exc).lower():
                    raise
    finally:
        con.close()


def ensure_fixed_by_column(db_path: str) -> None:
    """Add cli.fixed_by if the table exists and the column does not. No-op
    otherwise. Idempotent — a second call sees the column and returns."""
    con = sqlite3.connect(db_path)
    try:
        if _table_exists(con, "cli") and not _column_exists(con, "cli", "fixed_by"):
            try:
                con.execute("ALTER TABLE cli ADD COLUMN fixed_by TEXT")
                con.commit()
            except sqlite3.OperationalError as exc:
                # check-then-ALTER is not atomic: a concurrent caller can win
                # the race and add the column between our check and our ALTER.
                # "duplicate column name" then means the column already exists —
                # the desired end state — so treat it as success. Re-raise any
                # other operational error (locked, disk I/O, etc.).
                if "duplicate column" not in str(exc).lower():
                    raise
    finally:
        con.close()
