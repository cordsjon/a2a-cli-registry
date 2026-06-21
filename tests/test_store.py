import os
from core.store.db import init_db, get_session, with_file_lock
from core.models import Cli
from sqlmodel import select


def test_init_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "registry.db")
    engine = init_db(db_path)
    with get_session(engine) as s:
        s.add(Cli(slug="x", lang="python")); s.commit()
        assert s.exec(select(Cli)).one().slug == "x"


def test_file_lock_is_reentrant_safe(tmp_path):
    lock_path = str(tmp_path / "lock")
    with with_file_lock(lock_path):
        assert os.path.exists(lock_path)
