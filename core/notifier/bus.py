# core/notifier/bus.py
"""Webhook bus: HMAC-signed event delivery with per-subscriber sequence numbers
and a dead-letter path.

Public surface (all importable from this module):
  sign(secret, body) -> str
  enqueue_event(session, event_type, payload, clock, event_id) -> list[Delivery]
  deliver(delivery, subscriber, session, *, transport) -> None
  DEAD_LETTER_THRESHOLD: int = 5
"""

import hashlib
import hmac
import json
import ipaddress
import socket
from urllib.parse import urlparse

from sqlmodel import select
from core.models import Subscriber, Delivery

SCHEMA_VERSION = 1
DEAD_LETTER_THRESHOLD = 5

# Default timeout (seconds) for outbound HTTP POST.
_HTTP_TIMEOUT = 10.0

# Private/loopback address blocks to block (SSRF guard).
_PRIVATE_PREFIXES = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
)


# ---------------------------------------------------------------------------
# HMAC helper
# ---------------------------------------------------------------------------

def sign(secret: str, body: bytes) -> str:
    """Return HMAC-SHA256 hex digest of *body* keyed with *secret*."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def _is_ssrf_target(url: str) -> bool:
    """Return True if *url* resolves to a private/loopback address."""
    try:
        host = urlparse(url).hostname or ""
        addr = ipaddress.ip_address(socket.gethostbyname(host))
        return any(addr in net for net in _PRIVATE_PREFIXES)
    except Exception:
        # Resolution failure -> treat as blocked (fail-safe).
        return True


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def enqueue_event(
    session,
    event_type: str,
    payload: dict,
    clock,
    event_id: str,
) -> list[Delivery]:
    """Create one Delivery row per enabled Subscriber, advancing each sub's seq.

    The delivery payload JSON includes ``schema_version``, ``event_id``,
    per-subscriber ``seq``, ``event_type``, and the caller-supplied ``payload``
    dict.  All writes are committed atomically before returning.
    """
    subs = session.exec(select(Subscriber).where(Subscriber.enabled == True)).all()  # noqa: E712
    deliveries: list[Delivery] = []
    for sub in subs:
        sub.seq += 1
        body = json.dumps({
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "seq": sub.seq,
            "event_type": event_type,
            "payload": payload,
        })
        d = Delivery(
            subscriber_id=sub.id,
            event_id=event_id,
            event_type=event_type,
            payload=body,
            attempts=0,
            delivered=False,
            dead_lettered=False,
        )
        session.add(sub)
        session.add(d)
        deliveries.append(d)
    session.commit()
    return deliveries


# ---------------------------------------------------------------------------
# Deliver (outbound HTTP POST, injectable transport for testing)
# ---------------------------------------------------------------------------

class _HttpxTransport:
    """Real transport backed by httpx with SSRF guard.

    SSRF guard resolves the hostname and blocks private/loopback addresses
    before making any outbound connection.
    """

    def post(self, url: str, *, content: bytes, headers: dict, timeout: float):
        if _is_ssrf_target(url):
            raise ValueError(f"SSRF guard blocked delivery to {url!r}")
        import httpx  # noqa: PLC0415
        return httpx.post(url, content=content, headers=headers, timeout=timeout)


_DEFAULT_TRANSPORT = _HttpxTransport()


def deliver(
    delivery: Delivery,
    subscriber: Subscriber,
    session,
    *,
    transport=None,
) -> None:
    """Attempt to POST *delivery* to *subscriber*.

    On success: sets ``delivered=True``.
    On any exception: increments ``attempts``; if ``attempts >= DEAD_LETTER_THRESHOLD``
    sets ``dead_lettered=True``.  Each delivery is isolated — exceptions are
    caught internally (bulkhead); they never propagate to callers.

    The HMAC signature is placed in the ``X-Hub-Signature-256`` header as
    ``sha256=<hex>``.  The subscriber secret is never logged.

    *transport* is an optional injectable test double that implements
    ``.post(url, *, content, headers, timeout)``.  The default transport
    includes an SSRF guard; injected transports are responsible for their own
    safety (tests use controlled fakes).
    """
    if transport is None:
        transport = _DEFAULT_TRANSPORT

    body: bytes = delivery.payload.encode()
    sig = "sha256=" + sign(subscriber.hmac_secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": sig,
    }

    try:
        resp = transport.post(
            subscriber.url,
            content=body,
            headers=headers,
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            delivery.delivered = True
        else:
            raise OSError(f"non-200 response: {resp.status_code}")
    except Exception:
        delivery.attempts += 1
        if delivery.attempts >= DEAD_LETTER_THRESHOLD:
            delivery.dead_lettered = True
    finally:
        session.add(delivery)
        session.commit()
