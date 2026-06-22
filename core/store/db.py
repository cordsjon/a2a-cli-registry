from contextlib import contextmanager
import portalocker
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool


def init_db(path: str):
    """Create the engine and all tables. Fail-closed: any error propagates,
    no half-created schema is silently accepted.

    Thread-safe config: the `serve` command holds ONE Session for the server
    lifetime while FastAPI runs sync `def` endpoints in an anyio threadpool.
    StaticPool reuses a single connection across threads and
    check_same_thread=False permits cross-thread use — without this, concurrent
    requests raise sqlite3.ProgrammingError. Mirrors the test db fixture config.
    """
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)   # idempotent, transactional per-table
    return engine


@contextmanager
def get_session(engine):
    with Session(engine) as session:
        yield session


@contextmanager
def with_file_lock(path: str):
    """Cross-platform advisory lock (portalocker, not fcntl)."""
    with open(path, "a") as fh:
        portalocker.lock(fh, portalocker.LOCK_EX)
        try:
            yield
        finally:
            portalocker.unlock(fh)
