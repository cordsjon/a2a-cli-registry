"""Real cross-process concurrency tests for the mutating CLI commands.

The unit suite exercises the DB through an in-memory StaticPool fixture, which
shares ONE connection and therefore never hits the cross-process serialization
path (file lock + SQLite busy-timeout) that production uses. These tests launch
actual subprocesses against a shared on-disk registry DB so the lock and the
busy-timeout are genuinely exercised — the gap the final review flagged as
"asserted but not proven."
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent

# Run the CLI exactly as an operator would, but in-process-free: a fresh Python
# interpreter per call so each gets its own engine/connection (StaticPool is
# per-process, so this is the only way to exercise true cross-process contention).
_RUNNER = "import sys; from core.cli.main import main; sys.exit(main())"


def _run_cli(args, env=None):
    return subprocess.run(
        [sys.executable, "-c", _RUNNER, *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _write_fleet_and_cfg(tmp_path, slugs):
    fleet = tmp_path / "fleet.json"
    fleet.write_text(json.dumps({"clis": [
        {"slug": s, "lang": "shell", "path": "/bin/echo"} for s in slugs
    ]}))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'cli_audit_path = "{fleet}"\n'
        '[vocabulary]\nregistered = []\n[vocabulary.aliases]\n'
    )
    return cfg


@pytest.mark.slow
def test_concurrent_probes_all_succeed_against_shared_db(tmp_path):
    """Several `probe` processes launched simultaneously against ONE on-disk DB
    must all exit 0 — the file lock serializes the writes and the busy-timeout
    absorbs low-level contention, so none crashes with SQLITE_BUSY."""
    cfg = _write_fleet_and_cfg(tmp_path, [f"cli{i}" for i in range(6)])
    db = tmp_path / "registry.db"

    # Seed the catalog once (single process, no contention).
    seed = _run_cli(["populate", "--db", str(db), "--config", str(cfg)])
    assert seed.returncode == 0, f"populate failed: {seed.stderr}"

    # Launch 4 probes concurrently against the same DB file.
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _RUNNER, "probe",
             "--db", str(db), "--config", str(cfg)],
            cwd=str(_REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    results = [(p.wait(timeout=60), p) for p in procs]

    for rc, p in results:
        out, err = p.communicate()
        assert rc == 0, f"a concurrent probe crashed (rc={rc}): {err}"
        # Each probe prints a valid JSON summary — proves it ran to completion,
        # not that it died mid-write.
        summary = json.loads(out)
        assert summary["probed"] == 6


@pytest.mark.slow
def test_populate_and_probe_concurrent_keep_db_consistent(tmp_path):
    """A `populate` and a `probe` racing on the same DB must both exit 0 and
    leave a consistent catalog — the shared <db>.lock prevents probe from
    committing rows that populate deleted mid-sweep."""
    cfg = _write_fleet_and_cfg(tmp_path, [f"cli{i}" for i in range(8)])
    db = tmp_path / "registry.db"

    # Seed first so probe has rows to walk.
    assert _run_cli(["populate", "--db", str(db), "--config", str(cfg)]).returncode == 0

    pop = subprocess.Popen(
        [sys.executable, "-c", _RUNNER, "populate",
         "--db", str(db), "--config", str(cfg)],
        cwd=str(_REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    prb = subprocess.Popen(
        [sys.executable, "-c", _RUNNER, "probe",
         "--db", str(db), "--config", str(cfg)],
        cwd=str(_REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    pop_out, pop_err = pop.communicate(timeout=60)
    prb_out, prb_err = prb.communicate(timeout=60)

    assert pop.returncode == 0, f"populate crashed under contention: {pop_err}"
    assert prb.returncode == 0, f"probe crashed under contention: {prb_err}"

    # Final state: a read-only overview must succeed and show all 8 CLIs —
    # proving the racing writers left the catalog intact, not half-written.
    ov = _run_cli(["overview", "--db", str(db)])
    assert ov.returncode == 0, f"overview failed on post-contention db: {ov.stderr}"
    for i in range(8):
        assert f"cli{i}" in ov.stdout
