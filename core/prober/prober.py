# core/prober/prober.py
import shlex
import subprocess

_MAX_OUTPUT = 65536


def probe_one(cmd: str, timeout: float = 10.0) -> str:
    """Run a health probe in isolation. 10s default timeout, killed on hang,
    output capped. Returns 'healthy' (exit 0) or 'unhealthy'. This is a HEALTH
    probe, not a managed-CLI invocation for a network caller."""
    try:
        proc = subprocess.run(
            shlex.split(cmd), capture_output=True, timeout=timeout,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return "unhealthy"
    except (OSError, ValueError):
        return "unhealthy"
    _ = (proc.stdout or "")[:_MAX_OUTPUT]
    return "healthy" if proc.returncode == 0 else "unhealthy"
