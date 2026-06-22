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


@pytest.mark.skipif(__import__("os").name != "posix",
                    reason="process-group kill is POSIX-only")
def test_probe_one_timeout_kills_child_process_tree(tmp_path):
    """F2 (Codex): a probe whose command spawns a child must kill the WHOLE
    tree on timeout, not just the direct PID. The command backgrounds a child
    that writes a sentinel after 3s; the parent is killed at 0.5s. With a
    process-group kill the orphaned child dies before it can write the file."""
    sentinel = tmp_path / "child-survived.txt"
    # Parent sleeps 30s (will time out); it first spawns a detached child that
    # waits 3s then touches the sentinel. shlex.split needs a real argv, so run
    # the whole thing via `sh -c`.
    child = f"import time,pathlib; time.sleep(3); pathlib.Path(r'{sentinel}').write_text('x')"
    cmd = (f"sh -c '{sys.executable} -c \"{child}\" & "
           f"{sys.executable} -c \"import time; time.sleep(30)\"'")
    result = probe_one(cmd, timeout=0.5)
    assert result == "unhealthy"
    # Wait past the child's 3s delay; if the group kill worked the child is gone.
    time.sleep(4.0)
    assert not sentinel.exists(), "child survived timeout — process tree not killed"


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


def _seed_cli(session, slug, lang="true", health_checked_at=None, health_status="unknown"):
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
    # _RaisingAdapter.health_cmd raises, so bad-cli falls into no_cmd -> unknown
    assert bad.health_status == "unknown"

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
    assert cli.health_status == "stale"
    assert summary["stale"] == 1


def test_probe_fleet_unknown_if_no_adapter_and_within_ttl(db, clock):
    """A CLI with no adapter and a recent health_checked_at stays UNKNOWN (not STALE)."""
    recent_ts = clock.now() - (_STALE_TTL_SECONDS // 2)  # within TTL
    _seed_cli(db, "fresh-no-adapter", lang="unknown-lang",
              health_checked_at=recent_ts, health_status="healthy")

    summary = probe_fleet(db, [_TrueAdapter()], clock)

    db.expire_all()
    cli = db.get(Cli, "fresh-no-adapter")
    assert cli.health_status == "unknown"
    assert summary["unknown"] == 1


def test_probe_fleet_custom_staleness_ttl_marks_stale(db, clock):
    """A custom (small) staleness_ttl marks STALE a CLI that would NOT be stale
    under the default — proves the param drives the cutoff, not the constant."""
    # 90s old: stale under ttl=60, NOT stale under the default 3600
    old_ts = clock.now() - 90
    _seed_cli(db, "edge", lang="unknown-lang",
              health_checked_at=old_ts, health_status="healthy")
    probe_fleet(db, [_TrueAdapter()], clock, staleness_ttl=60)
    db.expire_all()
    assert db.get(Cli, "edge").health_status == "stale"


def test_probe_fleet_default_ttl_does_not_mark_recent_stale(db, clock):
    """The SAME 90s-old CLI stays 'unknown' under the default TTL."""
    old_ts = clock.now() - 90
    _seed_cli(db, "edge2", lang="unknown-lang",
              health_checked_at=old_ts, health_status="healthy")
    probe_fleet(db, [_TrueAdapter()], clock)  # default staleness_ttl
    db.expire_all()
    assert db.get(Cli, "edge2").health_status == "unknown"


def test_probe_fleet_forwards_timeout_and_max_output(db, clock, monkeypatch):
    """probe_timeout + max_output_bytes are forwarded into probe_one."""
    captured = {}
    def fake_probe_one(cmd, timeout=10.0, max_output_bytes=65536):
        captured["timeout"] = timeout
        captured["max_output_bytes"] = max_output_bytes
        return "healthy"
    monkeypatch.setattr("core.prober.prober.probe_one", fake_probe_one)
    _seed_cli(db, "x", lang="true")
    probe_fleet(db, [_TrueAdapter()], clock, probe_timeout=3.0, max_output_bytes=1234)
    assert captured == {"timeout": 3.0, "max_output_bytes": 1234}


def test_probe_fleet_concurrency_sets_max_workers(db, clock, monkeypatch):
    """probe_concurrency sets ThreadPoolExecutor(max_workers=...)."""
    captured = {}
    import core.prober.prober as prober_mod
    RealPool = prober_mod.ThreadPoolExecutor
    def spy_pool(max_workers=None, **kw):
        captured["max_workers"] = max_workers
        return RealPool(max_workers=max_workers, **kw)
    monkeypatch.setattr(prober_mod, "ThreadPoolExecutor", spy_pool)
    _seed_cli(db, "y", lang="true")
    probe_fleet(db, [_TrueAdapter()], clock, concurrency=3)
    assert captured["max_workers"] == 3


def test_probe_fleet_skips_disabled_cli(db, clock, monkeypatch):
    """A CLI with enabled=False is never spawned (probe_one not called for it)."""
    spawned = []
    def fake_probe_one(cmd, timeout=10.0, max_output_bytes=65536):
        spawned.append(cmd)
        return "healthy"
    monkeypatch.setattr("core.prober.prober.probe_one", fake_probe_one)
    cli = _seed_cli(db, "off", lang="true")
    cli.enabled = False
    db.add(cli); db.commit()
    summary = probe_fleet(db, [_TrueAdapter()], clock)
    assert spawned == []                 # never spawned
    assert summary["probed"] == 0
