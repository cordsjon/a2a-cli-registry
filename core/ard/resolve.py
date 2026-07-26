"""ARD two-hop resolution (spec US-2). Stdlib-only; catalog content is UNTRUSTED.

Hop 1: <base>/.well-known/ai-catalog.json -> entry by media type (ARD §3.4:
entry url references the artifact DOCUMENT). Hop 2 (mcp only): fetch the
server-card document, return its `endpoint`.
"""
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

MAX_BODY_BYTES = 1_048_576
TYPE_MEDIA = {
    "mcp": "application/mcp-server-card+json",
    "a2a": "application/a2a-agent-card+json",
}


class ArdError(Exception):
    """One-line operator-facing failure; message is safe to print as-is."""


def _now() -> float:
    return time.monotonic()


def _check_scheme(url: str) -> None:
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ArdError(f"refusing url with scheme '{scheme}' (allowed: http, https): {url}")


def fetch_json(url: str, deadline: float, max_bytes: int = MAX_BODY_BYTES) -> dict:
    _check_scheme(url)
    remaining = deadline - _now()
    if remaining <= 0:
        raise ArdError("resolve deadline (10s) exceeded")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=remaining) as resp:
            if resp.status != 200:
                raise ArdError(f"GET {url} -> HTTP {resp.status}")
            body = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        raise ArdError(f"GET {url} -> HTTP {e.code}") from e
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
        raise ArdError(f"GET {url} failed: {getattr(e, 'reason', e)}") from e
    if len(body) > max_bytes:
        raise ArdError(f"GET {url}: body too large (> {max_bytes} bytes)")
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as e:
        raise ArdError(f"GET {url}: invalid JSON ({e.msg})") from e
    if not isinstance(doc, dict):
        raise ArdError(f"GET {url}: expected a JSON object")
    return doc


def _select_entry(catalog: dict, media_type: str) -> dict:
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise ArdError("catalog has no 'entries' array")
    matches = [e for e in entries
               if isinstance(e, dict) and e.get("type") == media_type and isinstance(e.get("url"), str)]
    if not matches:
        raise ArdError(f"no entry of type {media_type} in catalog")
    if len(matches) > 1:
        # spec US-2 step 2: first wins, warn on stderr
        print(f"ard-resolve: {len(matches)} entries of type {media_type}; using the first",
              file=sys.stderr)
    return matches[0]


def resolve(base_url: str, type_: str, deadline_s: float = 10.0) -> str:
    """Return the MCP endpoint (type_='mcp', two hops) or the agent-card
    document url (type_='a2a')."""
    _check_scheme(base_url)
    if type_ not in TYPE_MEDIA:
        raise ArdError(f"unknown --type '{type_}' (choose: {', '.join(TYPE_MEDIA)})")
    deadline = _now() + deadline_s
    catalog = fetch_json(f"{base_url.rstrip('/')}/.well-known/ai-catalog.json", deadline)
    entry = _select_entry(catalog, TYPE_MEDIA[type_])
    _check_scheme(entry["url"])
    if type_ == "a2a":
        return entry["url"]
    card = fetch_json(entry["url"], deadline)
    endpoint = card.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise ArdError(f"server-card at {entry['url']} has no 'endpoint' field")
    _check_scheme(endpoint)
    return endpoint
