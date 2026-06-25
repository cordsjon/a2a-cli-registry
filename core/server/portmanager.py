"""Cross-platform free-port resolution for the `serve` command.

The registry binds a single HTTP port for REST + A2A + MCP + the /overview UI.
On a busy dev box that port is often already taken (e.g. dagu on 8080), and a
bare `uvicorn.run` would die with "address already in use" before the user ever
sees the dashboard. `resolve_port` probes the requested port and, unless strict
mode is requested, walks upward to the first free port so `serve` is launch-and-
forget.

Pure stdlib socket probing — no new dependency, works on macOS and Windows.
"""
import socket


class NoFreePortError(RuntimeError):
    """Raised when no free port is found within the scan window (or in strict
    mode when the single requested port is already bound)."""


def _is_free(host: str, port: int) -> bool:
    """True if `host:port` can be bound right now.

    SO_REUSEADDR mirrors how uvicorn binds, so a port we report free is one
    uvicorn can actually take. We bind-and-close rather than connect-probe
    because connect() can't see a socket bound to a different interface, while
    bind() answers the only question that matters: can WE listen here.
    """
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(fam, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def resolve_port(host: str, port: int, *, strict: bool = False,
                 max_scan: int = 64) -> int:
    """Return a bindable port for `host`, starting at `port`.

    strict=True: only the requested port is acceptable; raise NoFreePortError if
    it is taken (use when a fixed published port is a hard requirement).

    Otherwise scan [port, port+max_scan) and return the first free port. The
    bind probe is advisory — there is an unavoidable race between probing and
    uvicorn's own bind — but it removes the common, deterministic collision.

    "0.0.0.0" / "::" are bind-all addresses; we probe them directly since that
    is exactly what uvicorn will bind.
    """
    if strict:
        if _is_free(host, port):
            return port
        raise NoFreePortError(
            f"port {port} on {host} is in use and --strict-port was set"
        )

    for candidate in range(port, port + max_scan):
        if _is_free(host, candidate):
            return candidate

    raise NoFreePortError(
        f"no free port found in [{port}, {port + max_scan}) on {host}"
    )
