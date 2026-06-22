# core/announcer/announcer.py
import json
import logging
import os

import httpx

# SSRF guard reused from the notifier bus (option a: internal import as-is).
# Both modules are internal; no public API boundary is crossed. Duplicating the
# logic would violate abstract-on-third and drift over time, so we import the
# private function directly rather than copy it.
from core.notifier.bus import _is_ssrf_target, sign

_log = logging.getLogger(__name__)


def announce(card_url: str, brokers: list[str], timeout: float = 10.0) -> list[bool]:
    """Self-register the agent card URL to each broker. Outbound timeout enforced.
    Returns per-broker success flags. Status checked before assuming success.
    One broker failure is isolated — the loop continues to remaining brokers.

    SSRF guard: brokers that resolve to private/loopback addresses are skipped
    (result=False, warning logged). Uses the same guard as core.notifier.bus.

    HMAC signing: if A2A_ANNOUNCE_SECRET is set in the environment, the request
    body is signed with HMAC-SHA256 and sent as ``X-Hub-Signature-256: sha256=<hex>``,
    mirroring the header format used by the notifier bus for webhook deliveries.
    """
    secret = os.environ.get("A2A_ANNOUNCE_SECRET")
    body_dict = {"card_url": card_url}
    body_bytes = json.dumps(body_dict, separators=(",", ":")).encode()

    results = []
    for broker in brokers:
        # SSRF guard: block private/loopback targets before any outbound connection.
        if _is_ssrf_target(broker):
            _log.warning(
                "announce: SSRF guard blocked broker %r for card %r", broker, card_url
            )
            results.append(False)
            continue

        headers = {"Content-Type": "application/json"}
        if secret:
            sig = "sha256=" + sign(secret, body_bytes)
            headers["X-Hub-Signature-256"] = sig

        try:
            resp = httpx.post(
                broker,
                content=body_bytes,
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
            )
            results.append(resp.status_code == 200)   # check status, no bare .json()
        except (httpx.HTTPError, OSError) as exc:
            _log.warning("announce: broker %r failed for card %r: %s", broker, card_url, exc)
            results.append(False)
    return results
