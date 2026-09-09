"""The `--db` default must point at the live registry, not a repo-local file.

Regression: `core/cli/main.py` and `core/planner/probe.py` defaulted `--db` to
the bare relative string "registry.db". The live service is launched by
~/.hermes/scripts/cli-registry-serve.sh with an explicit
`--db $HOME/.hermes/cli-registry.db`, so anyone running a registry command
WITHOUT `--db` silently operated on a stale repo-local copy instead
(479 rows, last written 2026-08-03, vs 572 live) -- reads returned wrong
answers and writes went somewhere nothing serves.

`tools/reclassify_*.py` already used the correct pattern (`default=None` then
expanduser of the hermes path); these two entrypoints never got migrated.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.cli.main import DEFAULT_DB, resolve_db


CANONICAL = Path.home() / ".hermes" / "cli-registry.db"


def test_default_db_is_the_live_registry():
    """A bare relative filename would resolve against the caller's cwd."""
    assert Path(DEFAULT_DB) == CANONICAL, (
        f"--db default is {DEFAULT_DB!r}; the live service is served from {CANONICAL}"
    )
    assert Path(DEFAULT_DB).is_absolute(), (
        "a relative default resolves against the caller's cwd, so the same "
        "command reads a different DB depending on where it is run"
    )


def test_default_db_is_not_the_repo_copy():
    """The stale in-repo registry.db must never be the implicit target."""
    repo_copy = Path(__file__).resolve().parent.parent / "registry.db"
    assert Path(DEFAULT_DB) != repo_copy


def test_explicit_db_argument_still_wins():
    """Fixing the default must not make --db unsettable."""
    assert resolve_db("/tmp/somewhere/else.db") == "/tmp/somewhere/else.db"


def test_registry_db_env_var_overrides_default(monkeypatch):
    """cli-registry-serve.sh already honors REGISTRY_DB; match that contract."""
    monkeypatch.setenv("REGISTRY_DB", "/tmp/from-env.db")
    assert resolve_db(None) == "/tmp/from-env.db"


def test_explicit_argument_beats_the_env_var(monkeypatch):
    """Precedence: explicit flag > env var > canonical default."""
    monkeypatch.setenv("REGISTRY_DB", "/tmp/from-env.db")
    assert resolve_db("/tmp/explicit.db") == "/tmp/explicit.db"


def test_resolve_db_expands_user_and_env(monkeypatch):
    """~ and $VARS in an operator-supplied path must not reach sqlite raw."""
    monkeypatch.setenv("SOME_DIR", "/tmp/xyz")
    assert resolve_db("~/a.db") == os.path.expanduser("~/a.db")
    assert resolve_db("$SOME_DIR/b.db") == "/tmp/xyz/b.db"


def test_probe_shares_the_same_default():
    """Both entrypoints must agree; two defaults is the bug in a new costume."""
    from core.planner.probe import DEFAULT_DB as PROBE_DEFAULT

    assert Path(PROBE_DEFAULT) == Path(DEFAULT_DB)
