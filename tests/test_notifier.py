import hmac
import hashlib
import json
import socket

import pytest
from sqlmodel import select

from core.models import Subscriber, Delivery
from core.notifier.bus import sign, enqueue_event, deliver, DEAD_LETTER_THRESHOLD, _is_ssrf_target


# ---------------------------------------------------------------------------
# sign
# ---------------------------------------------------------------------------

def test_sign_is_hmac_sha256():
    assert sign("secret", b"body") == hmac.new(b"secret", b"body", hashlib.sha256).hexdigest()


def test_sign_differs_per_secret():
    sig_a = sign("secret_a", b"body")
    sig_b = sign("secret_b", b"body")
    assert sig_a != sig_b


# ---------------------------------------------------------------------------
# enqueue_event
# ---------------------------------------------------------------------------

def test_enqueue_creates_one_delivery_per_subscriber_with_seq(db, clock):
    db.add(Subscriber(url="http://a", hmac_secret="s1", seq=0))
    db.add(Subscriber(url="http://b", hmac_secret="s2", seq=4))
    db.commit()
    deliveries = enqueue_event(db, "new_cli", {"slug": "x"}, clock, event_id="e1")
    assert len(deliveries) == 2
    seqs = sorted(d.event_id for d in deliveries)
    assert seqs == ["e1", "e1"]
    # each subscriber's seq advanced by 1
    subs = db.exec(select(Subscriber)).all()
    assert sorted(s.seq for s in subs) == [1, 5]


def test_enqueue_sets_schema_version_in_payload(db, clock):
    db.add(Subscriber(url="http://a", hmac_secret="s1", seq=0))
    db.commit()
    deliveries = enqueue_event(db, "new_cli", {"slug": "x"}, clock, event_id="e2")
    payload = json.loads(deliveries[0].payload)
    assert payload["schema_version"] == 1


def test_enqueue_skips_disabled_subscribers(db, clock):
    db.add(Subscriber(url="http://enabled", hmac_secret="s1", seq=0, enabled=True))
    db.add(Subscriber(url="http://disabled", hmac_secret="s2", seq=0, enabled=False))
    db.commit()
    deliveries = enqueue_event(db, "new_cli", {}, clock, event_id="e3")
    assert len(deliveries) == 1


def test_enqueue_delivery_starts_undelivered_not_dead_lettered(db, clock):
    db.add(Subscriber(url="http://a", hmac_secret="s1", seq=0))
    db.commit()
    deliveries = enqueue_event(db, "new_cli", {}, clock, event_id="e4")
    d = deliveries[0]
    assert d.delivered is False
    assert d.dead_lettered is False
    assert d.attempts == 0


# ---------------------------------------------------------------------------
# dead_letter_threshold constant
# ---------------------------------------------------------------------------

def test_dead_letter_threshold_is_five():
    assert DEAD_LETTER_THRESHOLD == 5


# ---------------------------------------------------------------------------
# deliver — tested with fake transport
# ---------------------------------------------------------------------------

class _OKTransport:
    """Fake transport that always returns 200."""
    def __init__(self):
        self.calls = []

    def post(self, url, *, content, headers, timeout):
        self.calls.append({"url": url, "content": content, "headers": headers})

        class _Resp:
            status_code = 200
        return _Resp()


class _FailTransport:
    """Fake transport that always raises (simulates network error)."""
    def post(self, url, *, content, headers, timeout):
        raise OSError("connection refused")


def test_deliver_success_marks_delivered(db, clock):
    sub = Subscriber(url="http://example.com/hook", hmac_secret="sec", seq=1)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    body = b'{"schema_version":1,"event_id":"e1"}'
    d = Delivery(
        subscriber_id=sub.id,
        event_id="e1",
        event_type="new_cli",
        payload=body.decode(),
        attempts=0,
        delivered=False,
        dead_lettered=False,
    )
    db.add(d)
    db.commit()

    transport = _OKTransport()
    deliver(d, sub, db, transport=transport)

    db.refresh(d)
    assert d.delivered is True
    assert d.dead_lettered is False
    assert len(transport.calls) == 1
    # Signature header must be present
    assert "X-Hub-Signature-256" in transport.calls[0]["headers"]


def test_deliver_sends_hmac_signature(db, clock):
    sub = Subscriber(url="http://example.com/hook", hmac_secret="mysecret", seq=1)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    body = b'{"event_id":"e5"}'
    d = Delivery(
        subscriber_id=sub.id,
        event_id="e5",
        event_type="new_cli",
        payload=body.decode(),
        attempts=0,
        delivered=False,
        dead_lettered=False,
    )
    db.add(d)
    db.commit()

    transport = _OKTransport()
    deliver(d, sub, db, transport=transport)

    expected_sig = "sha256=" + sign("mysecret", body)
    assert transport.calls[0]["headers"]["X-Hub-Signature-256"] == expected_sig


def test_deliver_increments_attempts_on_failure(db, clock):
    sub = Subscriber(url="http://example.com/hook", hmac_secret="sec", seq=1)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    d = Delivery(
        subscriber_id=sub.id,
        event_id="e6",
        event_type="new_cli",
        payload='{"event_id":"e6"}',
        attempts=0,
        delivered=False,
        dead_lettered=False,
    )
    db.add(d)
    db.commit()

    deliver(d, sub, db, transport=_FailTransport())

    db.refresh(d)
    assert d.attempts == 1
    assert d.delivered is False


def test_deliver_dead_letters_at_threshold(db, clock):
    sub = Subscriber(url="http://example.com/hook", hmac_secret="sec", seq=1)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    d = Delivery(
        subscriber_id=sub.id,
        event_id="e7",
        event_type="new_cli",
        payload='{"event_id":"e7"}',
        attempts=DEAD_LETTER_THRESHOLD - 1,  # one more failure -> dead-letter
        delivered=False,
        dead_lettered=False,
    )
    db.add(d)
    db.commit()

    deliver(d, sub, db, transport=_FailTransport())

    db.refresh(d)
    assert d.dead_lettered is True
    assert d.attempts == DEAD_LETTER_THRESHOLD


def test_deliver_does_not_dead_letter_before_threshold(db, clock):
    sub = Subscriber(url="http://example.com/hook", hmac_secret="sec", seq=1)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    d = Delivery(
        subscriber_id=sub.id,
        event_id="e8",
        event_type="new_cli",
        payload='{"event_id":"e8"}',
        attempts=DEAD_LETTER_THRESHOLD - 2,  # still below threshold after this failure
        delivered=False,
        dead_lettered=False,
    )
    db.add(d)
    db.commit()

    deliver(d, sub, db, transport=_FailTransport())

    db.refresh(d)
    assert d.dead_lettered is False
    assert d.attempts == DEAD_LETTER_THRESHOLD - 1


def test_deliver_one_failure_does_not_affect_other_subscriber(db, clock):
    """Bulkhead: failure for one subscriber does not block another."""
    sub_a = Subscriber(url="http://a.example.com/hook", hmac_secret="sa", seq=1)
    sub_b = Subscriber(url="http://b.example.com/hook", hmac_secret="sb", seq=1)
    db.add(sub_a)
    db.add(sub_b)
    db.commit()
    db.refresh(sub_a)
    db.refresh(sub_b)

    d_a = Delivery(subscriber_id=sub_a.id, event_id="e9", event_type="t",
                   payload='{}', attempts=0, delivered=False, dead_lettered=False)
    d_b = Delivery(subscriber_id=sub_b.id, event_id="e9", event_type="t",
                   payload='{}', attempts=0, delivered=False, dead_lettered=False)
    db.add(d_a)
    db.add(d_b)
    db.commit()

    transport_ok = _OKTransport()
    deliver(d_a, sub_a, db, transport=_FailTransport())
    deliver(d_b, sub_b, db, transport=transport_ok)

    db.refresh(d_a)
    db.refresh(d_b)
    assert d_a.delivered is False
    assert d_b.delivered is True


# ---------------------------------------------------------------------------
# SSRF guard — network-free tests using monkeypatched getaddrinfo
# ---------------------------------------------------------------------------

def _make_getaddrinfo(ip: str):
    """Return a getaddrinfo stub that resolves any host to *ip*."""
    import socket as _socket
    family = _socket.AF_INET6 if ":" in ip else _socket.AF_INET
    def _stub(host, port, *args, **kwargs):  # noqa: ANN202
        return [(family, _socket.SOCK_STREAM, 6, "", (ip, 0))]
    return _stub


def test_ssrf_blocks_zero_address(monkeypatch):
    """0.0.0.0 is in 0.0.0.0/8 and must be blocked."""
    monkeypatch.setattr(socket, "getaddrinfo", _make_getaddrinfo("0.0.0.0"))
    assert _is_ssrf_target("http://anything.example.com/hook") is True


def test_ssrf_blocks_loopback_via_hostname(monkeypatch):
    """A hostname resolving to 127.0.0.1 must be blocked (no real DNS)."""
    monkeypatch.setattr(socket, "getaddrinfo", _make_getaddrinfo("127.0.0.1"))
    assert _is_ssrf_target("http://internal.corp/hook") is True


def test_ssrf_blocks_ipv6_loopback(monkeypatch):
    """A hostname resolving to ::1 must be blocked."""
    monkeypatch.setattr(socket, "getaddrinfo", _make_getaddrinfo("::1"))
    assert _is_ssrf_target("http://internal.corp/hook") is True


def test_ssrf_allows_public_address(monkeypatch):
    """A hostname resolving to a public routable IP must NOT be blocked."""
    monkeypatch.setattr(socket, "getaddrinfo", _make_getaddrinfo("93.184.216.34"))
    assert _is_ssrf_target("http://example.com/hook") is False


# ---------------------------------------------------------------------------
# FIX 3: success-path commit failure must not propagate (bulkhead contract)
# ---------------------------------------------------------------------------

def test_deliver_success_path_commit_failure_does_not_propagate(db, clock, monkeypatch):
    """If session.commit() raises on the success path, deliver() must NOT propagate
    the exception to the caller (bulkhead contract from docstring)."""
    sub = Subscriber(url="http://example.com/hook", hmac_secret="sec", seq=1)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    d = Delivery(
        subscriber_id=sub.id,
        event_id="e_commit_fail",
        event_type="new_cli",
        payload='{"event_id":"e_commit_fail"}',
        attempts=0,
        delivered=False,
        dead_lettered=False,
    )
    db.add(d)
    db.commit()

    call_count = {"n": 0}
    original_commit = db.commit

    def _failing_commit():
        call_count["n"] += 1
        # First call: the delivery row commit before transport (let pass)
        # Second call: the success-path commit (raise to simulate failure)
        if call_count["n"] >= 2:
            raise OSError("simulated commit failure on success path")
        return original_commit()

    monkeypatch.setattr(db, "commit", _failing_commit)

    transport = _OKTransport()
    # Must not raise — bulkhead must swallow the commit failure
    deliver(d, sub, db, transport=transport)
    # Transport was called (the send happened)
    assert len(transport.calls) == 1


# ---------------------------------------------------------------------------
# seq atomic-increment correctness
# ---------------------------------------------------------------------------

def test_enqueue_seq_per_subscriber_independence(db, clock):
    """Confirm atomic increment yields correct independent values per subscriber.

    Sub A starts at seq=0, sub B at seq=4.
    After one enqueue_event: A→1, B→5.
    This is the primary regression check for the SQL-level atomic increment.
    """
    db.add(Subscriber(url="http://a", hmac_secret="s1", seq=0))
    db.add(Subscriber(url="http://b", hmac_secret="s2", seq=4))
    db.commit()

    deliveries = enqueue_event(db, "test_event", {"k": "v"}, clock, event_id="seq-test")
    assert len(deliveries) == 2

    subs = db.exec(select(Subscriber)).all()
    seq_map = {s.url: s.seq for s in subs}
    assert seq_map["http://a"] == 1
    assert seq_map["http://b"] == 5

    # The seq embedded in the delivery payload must match the subscriber's committed seq.
    payload_seqs = sorted(json.loads(d.payload)["seq"] for d in deliveries)
    assert payload_seqs == [1, 5]
