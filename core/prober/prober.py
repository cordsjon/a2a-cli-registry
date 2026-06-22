# core/prober/prober.py
import shlex
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlmodel import select
from core.models import Cli
from core.discovery.base import CliRecord

_STALE_TTL_SECONDS = 3600

# Default output cap matching the config knob max_probe_output_bytes.
# Health is determined solely by exit code; we cap output to bound memory.
_DEFAULT_MAX_OUTPUT_BYTES = 65536


def _drain_bounded(pipe, max_bytes: int) -> None:
    """Read and discard at most max_bytes from *pipe*, then stop.

    Runs in a daemon thread. When the main thread kills the child process the
    pipe closes and this thread exits naturally. The bounded read prevents a
    runaway child from consuming unbounded memory.
    """
    try:
        remaining = max_bytes
        while remaining > 0:
            chunk = pipe.read1(min(remaining, 4096))  # type: ignore[attr-defined]
            if not chunk:
                break
            remaining -= len(chunk)
        # Drain any remaining bytes without storing them so the child is never
        # blocked on a full pipe write (avoids the write-block deadlock).
        while pipe.read1(4096):  # type: ignore[attr-defined]
            pass
    except OSError:
        pass


def probe_one(cmd: str, timeout: float = 10.0,
              max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES) -> str:
    """Run a health probe in isolation. 10s default timeout, killed on hang.
    Returns 'healthy' (exit 0) or 'unhealthy'.

    Output cap: a daemon thread drains stdout/stderr but stores at most
    max_output_bytes bytes so a runaway CLI cannot exhaust memory. Health is
    determined solely by exit code; captured bytes are discarded. proc.wait
    enforces the wall-time budget; on timeout the child is killed, which closes
    the pipe and unblocks the drain thread.

    This is a HEALTH probe, not a managed-CLI invocation for a network caller."""
    try:
        proc = subprocess.Popen(
            shlex.split(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except (OSError, ValueError):
        return "unhealthy"

    # Start daemon drain thread before waiting so the pipe never fills and
    # blocks the child (which would prevent proc.wait from returning).
    drain_thread = None
    if proc.stdout:
        drain_thread = threading.Thread(
            target=_drain_bounded,
            args=(proc.stdout, max_output_bytes),
            daemon=True,
        )
        drain_thread.start()

    timed_out = False
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out = True
    finally:
        if proc.stdout:
            proc.stdout.close()
        if drain_thread is not None:
            drain_thread.join(timeout=2.0)

    if timed_out:
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


def probe_fleet(session, adapters, clock, concurrency: int = 8,
                probe_timeout: float = 10.0,
                max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
                staleness_ttl: int = _STALE_TTL_SECONDS) -> dict:
    """Probe all CLIs in the session using bounded concurrency.

    - Finds the health command for each CLI via its adapter.
    - Calls probe_one for CLIs with a command (thread pool, I/O-bound).
    - Skips CLIs with enabled=False.
    - Marks CLIs with no probeable command as unknown; if their
      health_checked_at is older than staleness_ttl, marks stale.
    - DB writes happen on the main thread (SQLModel sessions are not thread-safe).
    - Returns a summary dict with counts by final state.

    Threading choice: ThreadPoolExecutor because probe_one is subprocess-bound
    (pure I/O wait). Each future's exception is caught individually so one
    failing probe does not abort others. Session writes are kept on the main
    thread after all futures complete.
    """
    now = clock.now()
    clis = session.exec(select(Cli)).all()
    clis = [c for c in clis if c.enabled]

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
            pool.submit(probe_one, cmd, probe_timeout, max_output_bytes): cli.slug
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
        if checked is not None and (now - checked) > staleness_ttl:
            cli.health_status = "stale"
            session.add(cli)
            counts["stale"] += 1
        else:
            cli.health_status = "unknown"
            session.add(cli)
            counts["unknown"] += 1

    session.commit()
    return counts
