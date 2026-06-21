from contextlib import contextmanager
import portalocker
from sqlmodel import SQLModel, Session, create_engine


def init_db(path: str):
    """Create the engine and all tables. Fail-closed: any error propagates,
    no half-created schema is silently accepted."""
    engine = create_engine(f"sqlite:///{path}")
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
