# core/prober/prober.py
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlmodel import select
from core.models import Cli
from core.discovery.base import CliRecord

_STALE_TTL_SECONDS = 3600


def probe_one(cmd: str, timeout: float = 10.0) -> str:
    """Run a health probe in isolation. 10s default timeout, killed on hang.
    Returns 'healthy' (exit 0) or 'unhealthy'.

    subprocess.run kills the child process on TimeoutExpired (verified in
    CPython source: on timeout it calls process.kill() then process.wait()
    before re-raising). No additional kill() needed here.

    This is a HEALTH probe, not a managed-CLI invocation for a network caller."""
    try:
        proc = subprocess.run(
            shlex.split(cmd), capture_output=True, timeout=timeout,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return "unhealthy"
    except (OSError, ValueError):
        return "unhealthy"
    return "healthy" if proc.returncode == 0 else "unhealthy"


def _cli_to_record(cli: Cli) -> CliRecord:
    """Build a minimal CliRecord from a Cli row for adapter dispatch."""
    return CliRecord(
        slug=cli.slug,
        lang=cli.lang,
        path=cli.path or "",
        bucket=cli.bucket,
        project=cli.project,
        description=cli.description,
        declared_capability=None,
        source_class=cli.source_class,
        source_run_id=cli.source_run_id,
    )


def _find_adapter(cli: Cli, adapters):
    rec = _cli_to_record(cli)
    for adapter in adapters:
        if adapter.detect(rec):
            return adapter, rec
    return None, None


def probe_fleet(session, adapters, clock, concurrency: int = 8) -> dict:
    """Probe all CLIs in the session using bounded concurrency.

    - Finds the health command for each CLI via its adapter.
    - Calls probe_one for CLIs with a command (thread pool, I/O-bound).
    - Marks CLIs with no probeable command as UNKNOWN; if their
      health_checked_at is older than _STALE_TTL_SECONDS, marks STALE.
    - DB writes happen on the main thread (SQLModel sessions are not thread-safe).
    - Returns a summary dict with counts by final state.

    Threading choice: ThreadPoolExecutor because probe_one is subprocess-bound
    (pure I/O wait). Each future's exception is caught individually so one
    failing probe does not abort others. Session writes are kept on the main
    thread after all futures complete.
    """
    now = clock.now()
    clis = session.exec(select(Cli)).all()

    # --- Phase 1: partition CLIs into probeable vs. unprobeable ---
    to_probe: list[tuple[Cli, str]] = []   # (cli, cmd)
    no_cmd: list[Cli] = []

    for cli in clis:
        try:
            adapter, rec = _find_adapter(cli, adapters)
            if adapter is None:
                no_cmd.append(cli)
                continue
            cmd = adapter.health_cmd(rec)
            if not cmd:
                no_cmd.append(cli)
            else:
                to_probe.append((cli, cmd))
        except Exception:
            no_cmd.append(cli)

    # --- Phase 2: run probes concurrently, one future per CLI ---
    results: dict[str, str] = {}   # slug -> status string

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        future_to_slug = {
            pool.submit(probe_one, cmd): cli.slug
            for cli, cmd in to_probe
        }
        for future in as_completed(future_to_slug):
            slug = future_to_slug[future]
            try:
                results[slug] = future.result()
            except Exception:
                # Isolation: one probe crashing doesn't abort the fleet.
                results[slug] = "unhealthy"

    # --- Phase 3: write results on main thread ---
    counts = {"probed": 0, "healthy": 0, "unhealthy": 0, "stale": 0, "unknown": 0}

    for cli, _cmd in to_probe:
        status = results.get(cli.slug, "unhealthy")
        cli.health_status = status
        cli.health_checked_at = now
        session.add(cli)
        counts["probed"] += 1
        counts[status] = counts.get(status, 0) + 1

    for cli in no_cmd:
        checked = cli.health_checked_at
        if checked is not None and (now - checked) > _STALE_TTL_SECONDS:
            cli.health_status = "STALE"
            session.add(cli)
            counts["stale"] += 1
        else:
            cli.health_status = "UNKNOWN"
            session.add(cli)
            counts["unknown"] += 1

    session.commit()
    return counts
