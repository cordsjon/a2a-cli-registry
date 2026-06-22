import sys
import time
import pytest
from core.prober.prober import probe_one, probe_fleet, _STALE_TTL_SECONDS
from core.models import Cli
from core.discovery.base import CliRecord


# ---------------------------------------------------------------------------
# Existing probe_one tests (must not be weakened)
# ---------------------------------------------------------------------------

def test_probe_healthy_on_zero_exit():
    assert probe_one("true") == "healthy"


def test_probe_unhealthy_on_nonzero_exit():
    assert probe_one("false") == "unhealthy"


def test_probe_unhealthy_on_timeout():
    # sleeps longer than the timeout -> killed -> unhealthy, does not hang
    assert probe_one("sleep 5", timeout=0.5) == "unhealthy"


# ---------------------------------------------------------------------------
# Output cap tests (new — SECURITY.md "output cap" claim)
# ---------------------------------------------------------------------------

def test_probe_one_caps_runaway_output():
    """A command that emits far more than max_output_bytes still returns a
    valid verdict promptly without buffering the full output in memory.

    We use a small cap (1000 bytes) against a command that prints 200 000 bytes
    so the cap fires almost immediately. Exit 0 -> healthy.
    The test asserts: correct verdict, completes well under the 10s timeout."""
    cmd = f"{sys.executable} -c \"print('x'*200000)\""
    start = time.monotonic()
    result = probe_one(cmd, timeout=10.0, max_output_bytes=1000)
    elapsed = time.monotonic() - start
    assert result == "healthy", f"expected healthy, got {result!r}"
    assert elapsed < 5.0, f"took {elapsed:.2f}s — possible hang"


def test_probe_one_healthy_small_output():
    """Normal command with small output exits 0 -> healthy."""
    cmd = f"{sys.executable} -c \"print('ok')\""
    assert probe_one(cmd) == "healthy"


def test_probe_one_timeout_returns_unhealthy():
    """A hanging command with a short timeout is killed and returns unhealthy
    promptly — must not wait the full sleep duration."""
    cmd = f"{sys.executable} -c \"import time; time.sleep(30)\""
    start = time.monotonic()
    result = probe_one(cmd, timeout=0.5)
    elapsed = time.monotonic() - start
    assert result == "unhealthy", f"expected unhealthy, got {result!r}"
    assert elapsed < 5.0, f"took {elapsed:.2f}s — kill did not fire"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _TrueAdapter:
    """Adapter that detects all CLIs with lang='true' and returns 'true' as cmd."""
    def detect(self, rec: CliRecord) -> bool:
        return rec.lang == "true"

    def health_cmd(self, rec: CliRecord) -> str:
        return "true"

    def launch_spec(self, rec: CliRecord) -> dict:
        return {}

    def infer_capability(self, rec: CliRecord):
        return None


class _FalseAdapter:
    """Adapter that detects lang='false' and returns 'false' (exit 1) as cmd."""
    def detect(self, rec: CliRecord) -> bool:
        return rec.lang == "false"

    def health_cmd(self, rec: CliRecord) -> str:
        return "false"

    def launch_spec(self, rec: CliRecord) -> dict:
        return {}

    def infer_capability(self, rec: CliRecord):
        return None


class _RaisingAdapter:
    """Adapter that detects lang='raises' but whose health_cmd raises."""
    def detect(self, rec: CliRecord) -> bool:
        return rec.lang == "raises"

    def health_cmd(self, rec: CliRecord) -> str:
        raise RuntimeError("simulated adapter failure")

    def launch_spec(self, rec: CliRecord) -> dict:
        return {}

    def infer_capability(self, rec: CliRecord):
        return None


def _seed_cli(session, slug, lang="true", health_checked_at=None, health_status="UNKNOWN"):
    cli = Cli(slug=slug, lang=lang, health_checked_at=health_checked_at,
              health_status=health_status)
    session.add(cli)
    session.commit()
    return cli


# ---------------------------------------------------------------------------
# New probe_fleet tests
# ---------------------------------------------------------------------------

def test_probe_fleet_writes_health_status_and_timestamp(db, clock):
    """A CLI with a health command that exits 0 becomes 'healthy' with timestamp set."""
    _seed_cli(db, "mypkg", lang="true")

    summary = probe_fleet(db, [_TrueAdapter()], clock)

    db.expire_all()
    cli = db.get(Cli, "mypkg")
    assert cli.health_status == "healthy"
    assert cli.health_checked_at == clock.now()
    assert summary["healthy"] == 1
    assert summary["probed"] == 1


def test_probe_fleet_isolation_one_failure_does_not_abort(db, clock):
    """One CLI's adapter raising must not abort probing the other CLI."""
    _seed_cli(db, "good-cli", lang="true")
    _seed_cli(db, "bad-cli", lang="raises")

    # Should not raise; bad-cli goes UNKNOWN (adapter error at classify time).
    summary = probe_fleet(db, [_TrueAdapter(), _RaisingAdapter()], clock)

    db.expire_all()
    good = db.get(Cli, "good-cli")
    assert good.health_status == "healthy", "good-cli must still be probed successfully"
    assert good.health_checked_at == clock.now()

    bad = db.get(Cli, "bad-cli")
    # _RaisingAdapter.health_cmd raises, so bad-cli falls into no_cmd -> UNKNOWN
    assert bad.health_status == "UNKNOWN"

    assert summary["healthy"] == 1


def test_probe_fleet_marks_stale_past_ttl(db, clock):
    """A CLI with no probeable command whose last check is past the TTL becomes STALE."""
    old_ts = clock.now() - _STALE_TTL_SECONDS - 1  # just beyond TTL
    _seed_cli(db, "stale-cli", lang="unknown-lang",
              health_checked_at=old_ts, health_status="healthy")

    # No adapter matches lang="unknown-lang"
    summary = probe_fleet(db, [_TrueAdapter()], clock)

    db.expire_all()
    cli = db.get(Cli, "stale-cli")
    assert cli.health_status == "STALE"
    assert summary["stale"] == 1


def test_probe_fleet_unknown_if_no_adapter_and_within_ttl(db, clock):
    """A CLI with no adapter and a recent health_checked_at stays UNKNOWN (not STALE)."""
    recent_ts = clock.now() - (_STALE_TTL_SECONDS // 2)  # within TTL
    _seed_cli(db, "fresh-no-adapter", lang="unknown-lang",
              health_checked_at=recent_ts, health_status="healthy")

    summary = probe_fleet(db, [_TrueAdapter()], clock)

    db.expire_all()
    cli = db.get(Cli, "fresh-no-adapter")
    assert cli.health_status == "UNKNOWN"
    assert summary["unknown"] == 1
