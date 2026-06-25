import socket

import pytest

from core.server.portmanager import resolve_port, NoFreePortError, _is_free


def _bind_one(host="127.0.0.1"):
    """Bind an ephemeral port and return (socket, port). Caller keeps the socket
    open to hold the port; closing it frees the port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, 0))
    return s, s.getsockname()[1]


def test_free_port_returns_itself():
    held, port = _bind_one()
    held.close()  # now free
    assert resolve_port("127.0.0.1", port) == port


def test_taken_port_climbs_to_next_free():
    held, port = _bind_one()
    try:
        got = resolve_port("127.0.0.1", port, max_scan=64)
        assert got != port
        assert got > port
        assert _is_free("127.0.0.1", got)
    finally:
        held.close()


def test_strict_mode_raises_when_taken():
    held, port = _bind_one()
    try:
        with pytest.raises(NoFreePortError):
            resolve_port("127.0.0.1", port, strict=True)
    finally:
        held.close()


def test_strict_mode_returns_free_port():
    held, port = _bind_one()
    held.close()
    assert resolve_port("127.0.0.1", port, strict=True) == port


def test_exhausted_scan_window_raises():
    # A 1-wide window over a taken port has no free candidate.
    held, port = _bind_one()
    try:
        with pytest.raises(NoFreePortError):
            resolve_port("127.0.0.1", port, max_scan=1)
    finally:
        held.close()
