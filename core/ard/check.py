"""Catalog self-check (spec US-7). Pure HTTP — no DB, no lock (probe's write-lock
must NOT be contended by a read-only network check).

Two health tiers for the MCP endpoint (spec: '401 is alive' only proves the auth
gate exists): with A2A_BEARER_TOKEN -> real MCP initialize handshake ('ok');
without -> 401 counts as 'alive-unverified' (visibly weaker)."""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from core.ard.resolve import ArdError, fetch_json, _now, TYPE_MEDIA, _check_scheme

_INIT_PAYLOAD = {
    "jsonrpc": "2.0", "method": "initialize", "id": 1,
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "ard-check", "version": "0.0.1"}},
}


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def _post_once(endpoint: str, token: str | None):
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(endpoint, method="POST", headers=headers,
                                 data=json.dumps(_INIT_PAYLOAD).encode())
    return urllib.request.urlopen(req, timeout=5)


def _endpoint_status(endpoint: str, token: str | None, _redirects: int = 1) -> str:
    """'ok' | 'alive-unverified' | raises ArdError.

    urllib does NOT auto-follow 307/308 on POST, and Starlette's mount for /mcp
    307-redirects to /mcp/ — so a server-card advertising the slash-less path
    would otherwise always read as FAIL. Follow at most one same-origin 307/308
    ourselves (untrusted card content: never follow cross-origin, never
    downgrade scheme, never loop).
    """
    try:
        with _post_once(endpoint, token) as resp:
            if token and resp.status == 200:
                return "ok"
            return "alive-unverified"
    except urllib.error.HTTPError as e:
        if e.code in (307, 308) and _redirects > 0:
            location = e.headers.get("Location") if e.headers else None
            if location:
                target = urljoin(endpoint, location)
                _check_scheme(target)
                if _same_origin(endpoint, target) and target != endpoint:
                    return _endpoint_status(target, token, _redirects - 1)
        if e.code == 401 and not token:
            return "alive-unverified"
        raise ArdError(f"POST {endpoint} -> HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise ArdError(f"POST {endpoint} failed: {getattr(e, 'reason', e)}") from e


def run_check(base_url: str) -> int:
    token = os.environ.get("A2A_BEARER_TOKEN") or None
    deadline = _now() + 10.0
    try:
        catalog = fetch_json(f"{base_url.rstrip('/')}/.well-known/ai-catalog.json", deadline)
    except ArdError as e:
        print(f"catalog FAIL: {e}")
        return 1
    failures = 0
    for entry in catalog.get("entries", []):
        ident = entry.get("identifier", "<no-identifier>")
        try:
            url = entry.get("url")
            if not isinstance(url, str) or not url:
                # schema allows a 'data' (inline) variant instead of 'url'
                raise ArdError("entry has no 'url' (data-inline entries are not supported by this check)")
            doc = fetch_json(url, deadline)
            if entry.get("type") == TYPE_MEDIA["a2a"]:
                if "name" not in doc or "url" not in doc:
                    raise ArdError("document is not an Agent Card (missing name/url)")
                print(f"{ident} ok")
            elif entry.get("type") == TYPE_MEDIA["mcp"]:
                endpoint = doc.get("endpoint")
                if not isinstance(endpoint, str) or not endpoint:
                    raise ArdError("server-card has no 'endpoint'")
                print(f"{ident} {_endpoint_status(endpoint, token)}")
            else:
                print(f"{ident} ok")   # unknown media type: reachable JSON is enough
        except ArdError as e:
            print(f"{ident} FAIL: {e}")
            failures += 1
    return 1 if failures else 0
