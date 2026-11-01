"""Does a row do real work? health_status only says it launches.

Runs a row's launch_spec.smoke against a copy of its fixture in a throwaway cwd,
with the environment a launcher can send. See docs/launch-spec.md."""
import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from sqlmodel import select

from core.models import Cli
from core.prober.prober import _DEFAULT_MAX_OUTPUT_BYTES, _POSIX, _kill_tree, _probe_env

_REPO_ROOT = Path(__file__).resolve().parents[2]
# An allowlist: a missing or misspelled side_effects must not run unattended.
_SAFE_SIDE_EFFECTS = {"none", "tmp"}
_DEFAULT_TIMEOUT = 60.0


def _gated(smoke: dict, allow_network: bool) -> bool:
    return not allow_network and smoke.get("side_effects") not in _SAFE_SIDE_EFFECTS


def _copy_fixture(fixture, cwd: str) -> bool:
    """Copy the fixture's contents into cwd. False when it does not exist."""
    if not fixture:
        return True
    source = Path(fixture)
    if not source.is_absolute():
        source = _REPO_ROOT / source
    if source.is_dir():
        shutil.copytree(source, cwd, dirs_exist_ok=True)
    elif source.is_file():
        shutil.copy(source, cwd)
    else:
        return False
    return True


def _read_bounded(pipe, max_bytes: int, out: list) -> None:
    """Keep at most max_bytes, then drain so the child never blocks on a full pipe."""
    try:
        remaining = max_bytes
        while chunk := pipe.read1(4096):
            out.append(chunk[:remaining])
            remaining -= len(out[-1])
    except (OSError, ValueError):
        pass        # the pipe closed under us: the child is gone


def _run(argv: list, cwd: str, timeout: float, max_output_bytes: int):
    """(exit code, stdout). Exit code None means it did not start or timed out."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, cwd=cwd, env=_probe_env(),
                                start_new_session=_POSIX)
    except (OSError, ValueError):
        return None, ""
    chunks: list = []
    reader = threading.Thread(target=_read_bounded, args=(proc.stdout, max_output_bytes, chunks),
                              daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.wait()
        code = None
    reader.join(timeout=2.0)
    proc.stdout.close()
    return code, b"".join(chunks).decode("utf-8", errors="replace")


def run_smoke(spec: dict, *, timeout: float, allow_network: bool = False,
              max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES) -> str:
    """'pass', 'fail', or 'unknown' when there is no smoke or it was not allowed
    to run. A broken spec is a 'fail': unknown would hide it among the unproven."""
    smoke = spec.get("smoke")
    if not smoke or _gated(smoke, allow_network):
        return "unknown"
    argv = smoke.get("argv")
    if not argv:
        return "fail"
    with tempfile.TemporaryDirectory(prefix="clireg-smoke-") as cwd:
        if not _copy_fixture(smoke.get("fixture"), cwd):
            return "fail"
        code, stdout = _run(argv, smoke.get("cwd") or cwd, smoke.get("timeout", timeout),
                            max_output_bytes)
        if code != smoke.get("expect_exit", 0):
            return "fail"
        pattern = smoke.get("expect_stdout_re")
        try:
            if pattern and not re.search(pattern, stdout):
                return "fail"
        except re.error:
            return "fail"
        expect_file = smoke.get("expect_file")
        if expect_file and not (Path(cwd) / expect_file).exists():
            return "fail"
    return "pass"


def _load_spec(cli: Cli) -> dict:
    try:
        spec = json.loads(cli.launch_spec or "{}")
    except ValueError:
        return {}       # 'install:<url>' placeholder rows are not specs
    return spec if isinstance(spec, dict) else {}


def smoke_rows(session, clock, slugs=(), timeout: float = _DEFAULT_TIMEOUT,
               allow_network: bool = False, dry_run: bool = False) -> dict:
    """Write work_status for the enabled rows, or the named ones. Never touches
    health_status. A gated row is not written at all: not running it says nothing
    about it, and a dated operator pass has to survive the next sweep."""
    now = clock.now()
    query = select(Cli).where(Cli.slug.in_(set(slugs))) if slugs else select(Cli)
    clis = [c for c in session.exec(query).all() if c.enabled]
    counts = {"pass": 0, "fail": 0, "unknown": 0, "dry_run": dry_run,
              "fail_slugs": [], "gated_network": []}
    for cli in sorted(clis, key=lambda c: c.slug):
        spec = _load_spec(cli)
        smoke = spec.get("smoke")
        if smoke and _gated(smoke, allow_network):
            counts["gated_network"].append(cli.slug)
            continue
        status = run_smoke(spec, timeout=timeout, allow_network=allow_network)
        counts[status] += 1
        if status == "fail":
            counts["fail_slugs"].append(cli.slug)
        if dry_run:
            continue
        cli.work_status = status
        if smoke:
            cli.work_checked_at = now
        session.add(cli)
        session.commit()    # per row: a long batch that dies keeps what it proved
    if slugs:
        counts["not_probed"] = sorted(set(slugs) - {c.slug for c in clis})
    return counts
