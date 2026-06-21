import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
def clock():
    """Injectable deterministic clock. Tests advance time explicitly."""
    class Clock:
        def __init__(self):
            self._now = 1_700_000_000.0  # fixed epoch seconds
        def now(self) -> float:
            return self._now
        def advance(self, seconds: float) -> None:
            self._now += seconds
    return Clock()


@pytest.fixture
def db():
    """In-memory SQLite session shared across one test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def spawn_spy(monkeypatch):
    """Asserts NO managed-CLI subprocess is spawned. The describe+plan-only guard."""
    calls = []
    import subprocess

    def _forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError(f"managed-CLI spawn attempted: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    return calls
