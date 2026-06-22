# core/announcer/announcer.py
import httpx


def announce(card_url: str, brokers: list[str], timeout: float = 10.0) -> list[bool]:
    """Self-register the agent card URL to each broker. Outbound timeout enforced.
    Returns per-broker success flags. Status checked before assuming success."""
    results = []
    for broker in brokers:
        try:
            resp = httpx.post(broker, json={"card_url": card_url}, timeout=timeout)
            results.append(resp.status_code == 200)   # check status, no bare .json()
        except httpx.HTTPError:
            results.append(False)
    return results
