"""Does a row do real work? health_status only says it launches.

Runs a row's launch_spec.smoke against a copy of its fixture in a throwaway cwd,
with the environment a launcher can send. See docs/launch-spec.md."""
import json
import os
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
_NETWORK_SIDE_EFFECTS = {"network", "spend"}
_DEFAULT_TIMEOUT = 60.0
_WRITABLE = ("/private/tmp", "/private/var/folders", "/dev", "~/.cache", "~/Library/Caches")
_TAIL_CHARS = 2000      # per stream, kept for a failing smoke only


def _gated(smoke: dict, allow_network: bool) -> bool:
    return not allow_network and smoke.get("side_effects") not in _SAFE_SIDE_EFFECTS


def _sandboxed(smoke: dict, argv: list, cwd: str) -> list:
    """Hold a smoke to what it declares: a tool that hardcodes a live path must fail
    here, not write to it. macOS only; elsewhere the declaration is only a promise.
    A smoke with its own cwd is a project's test suite, which writes in its checkout."""
    exe = shutil.which("sandbox-exec")
    if exe is None or smoke.get("cwd"):
        return argv
    roots = [os.path.realpath(os.path.expanduser(p)) for p in (cwd, *_WRITABLE)]
    allowed = " ".join(f'(subpath "{root}")' for root in roots)
    network = "" if smoke.get("side_effects") in _NETWORK_SIDE_EFFECTS else "(deny network*)"
    return [exe, "-p", f"(version 1)(allow default){network}(deny file-write*)(allow file-write* {allowed})", *argv]


def _copy_fixture(fixture, cwd: str) -> bool:
    """Copy the fixture's contents into cwd. False when it does not exist."""
    if not fixture:
        return True
    source = Path(fixture)
    if not source.is_absolute():
        source = _REPO_ROOT / source
    try:
        if source.is_dir():
            shutil.copytree(source, cwd, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy(source, cwd)
        else:
            return False
    except OSError:     # shutil.Error too: a symlink whose target moved must fail one row, not the sweep
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
    return _run_detail(argv, cwd, timeout, max_output_bytes)[:2]


def _run_detail(argv: list, cwd: str, timeout: float, max_output_bytes: int):
    """(exit code, stdout, stderr, error). Exit code None means it did not start or
    timed out, and error says which. stderr is for the reader of a failure only."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, env=_probe_env(),
                                start_new_session=_POSIX)
    except (OSError, ValueError) as exc:
        return None, "", "", f"did not start: {exc}"
    streams = {"stdout": [], "stderr": []}
    readers = [threading.Thread(target=_read_bounded, args=(getattr(proc, name), max_output_bytes, chunks),
                                daemon=True) for name, chunks in streams.items()]
    for reader in readers:
        reader.start()
    error = ""
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.wait()
        code, error = None, f"timed out after {timeout}s"
    for reader in readers:
        reader.join(timeout=2.0)
    proc.stdout.close()
    proc.stderr.close()
    out, err = (b"".join(c).decode("utf-8", errors="replace") for c in streams.values())
    return code, out, err, error


def run_smoke(spec: dict, *, timeout: float, allow_network: bool = False,
              max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES) -> str:
    """'pass', 'fail', or 'unknown' when there is no smoke or it was not allowed
    to run. A broken spec is a 'fail': unknown would hide it among the unproven."""
    return smoke_result(spec, timeout=timeout, allow_network=allow_network,
                        max_output_bytes=max_output_bytes)[0]


def smoke_result(spec: dict, *, timeout: float, allow_network: bool = False,
                 max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES) -> tuple:
    """(status, reason, tails) as run_smoke. For a 'fail', reason names the check that
    failed and tails holds the last _TAIL_CHARS of stdout and stderr once the command
    ran; otherwise both are empty. A transient failure is only diagnosable from these."""
    smoke = spec.get("smoke")
    if not smoke or _gated(smoke, allow_network):
        return "unknown", "", {}
    argv = smoke.get("argv")
    if not argv:
        return "fail", "smoke has no argv", {}
    with tempfile.TemporaryDirectory(prefix="clireg-smoke-") as cwd:
        if not _copy_fixture(smoke.get("fixture"), cwd):
            return "fail", f"fixture not copied: {smoke.get('fixture')}", {}
        code, stdout, stderr, error = _run_detail(_sandboxed(smoke, argv, cwd), smoke.get("cwd") or cwd,
                                                  smoke.get("timeout", timeout), max_output_bytes)
        reason = _failed_check(smoke, cwd, code, error, stdout, max_output_bytes)
    if not reason:
        return "pass", "", {}
    return "fail", reason, {"stdout": stdout[-_TAIL_CHARS:], "stderr": stderr[-_TAIL_CHARS:]}


def _failed_check(smoke: dict, cwd: str, code, error: str, stdout: str, max_output_bytes: int) -> str:
    """The first check the run fails, or "" when it passes them all."""
    expect_exit = smoke.get("expect_exit", 0)
    if error:
        return error
    if code != expect_exit:
        return f"exit {code}, expected {expect_exit}"
    expect_file = smoke.get("expect_file")
    if expect_file and not (Path(cwd) / expect_file).exists():
        return f"expect_file {expect_file} not written"
    pattern, file_pattern = smoke.get("expect_stdout_re"), smoke.get("expect_file_re")
    try:
        if pattern and not re.search(pattern, stdout):
            return "stdout did not match expect_stdout_re"
        if file_pattern:
            text = (Path(cwd) / expect_file).read_bytes()[:max_output_bytes].decode("utf-8", "replace")
            if not re.search(file_pattern, text):
                return f"{expect_file} did not match expect_file_re"
    except (re.error, OSError, TypeError) as exc:      # TypeError: expect_file_re with no expect_file
        return f"check could not run: {exc}"
    return ""


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
    about it, and a dated operator pass has to survive the next sweep. A
    not_standalone row is unknown and its smoke does not run: no launcher can reach
    the row, so a pass would only prove a test file."""
    now = clock.now()
    query = select(Cli).where(Cli.slug.in_(set(slugs))) if slugs else select(Cli)
    clis = [c for c in session.exec(query).all() if c.enabled]
    counts = {"pass": 0, "fail": 0, "unknown": 0, "dry_run": dry_run,
              "fail_slugs": [], "fail_detail": {}, "gated_network": []}
    for cli in sorted(clis, key=lambda c: c.slug):
        spec = {} if cli.not_standalone else _load_spec(cli)
        smoke = spec.get("smoke")
        if smoke and _gated(smoke, allow_network):
            counts["gated_network"].append(cli.slug)
            continue
        status, reason, tails = smoke_result(spec, timeout=timeout, allow_network=allow_network)
        counts[status] += 1
        if status == "fail":
            counts["fail_slugs"].append(cli.slug)
            counts["fail_detail"][cli.slug] = {"reason": reason, "stdout": "", "stderr": "", **tails}
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
