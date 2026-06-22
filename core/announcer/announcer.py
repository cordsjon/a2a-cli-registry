# core/announcer/announcer.py
import logging

import httpx

_log = logging.getLogger(__name__)


def announce(card_url: str, brokers: list[str], timeout: float = 10.0) -> list[bool]:
    """Self-register the agent card URL to each broker. Outbound timeout enforced.
    Returns per-broker success flags. Status checked before assuming success.
    One broker failure is isolated — the loop continues to remaining brokers."""
    results = []
    for broker in brokers:
        try:
            resp = httpx.post(
                broker,
                json={"card_url": card_url},
                timeout=timeout,
                follow_redirects=False,
            )
            results.append(resp.status_code == 200)   # check status, no bare .json()
        except Exception as exc:
            _log.warning("announce: broker %r failed for card %r: %s", broker, card_url, exc)
            results.append(False)
    return results
