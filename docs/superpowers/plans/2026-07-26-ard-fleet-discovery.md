# ARD Fleet Discovery (a2a-cli-registry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve an ARD v1.0 catalog + MCP server-card at well-known URLs, add an `ard-resolve` CLI subcommand (two-hop resolution, consumer config emit, `--check` self-health), and a schema-drift script.

**Architecture:** Reference-only catalog (Option C): `/.well-known/ai-catalog.json` lists two entries whose `url`s point at artifact *documents* (`agent-card.json`, `mcp-server-card.json`) per ARD §3.4. Consumers do two-hop resolution: catalog → server-card → `endpoint`. Builders are pure functions in `core/cardgen/` (clone-shape of `card.py`); the resolver is stdlib-only in `core/ard/`.

**Tech Stack:** Python 3.11+, FastAPI (existing), stdlib `urllib.request` for the resolver (runtime stays dependency-free), `jsonschema` 4.26.0 (already in dev extras) for tests only.

**Scope note:** This plan covers the a2a-cli-registry USs only (US-1, US-2, US-7, US-8 script, US-Docs). US-3 (hermes-adapter), US-4 (OpenWorker), US-5 (beehive) are separate plans in their owning repos, per the spec's sequencing.
Spec: `docs/superpowers/specs/2026-07-26-ard-fleet-discovery-design.md` (rev 61b0ed9).

## Global Constraints

- **No new runtime dependencies.** Resolver uses stdlib `urllib.request`. `jsonschema>=4.0` is already in `[project.optional-dependencies] dev` — tests only.
- **Flat argparse, no subparsers.** `core/cli/main.py:91-121` has ONE positional `command` with `choices=[...]`. New flags are global; help strings prefixed `[ard-resolve]` (existing convention: `[serve]`, `[remediate]`). Do NOT migrate to subparsers.
- **`ard-resolve` is lock-free and DB-free.** Never touch `with_file_lock` / sessions (that's `probe`'s domain).
- **Secrets:** no token is ever read, stored, or printed by resolver/emit code. Emitted snippets reference `$A2A_BEARER_TOKEN` / SecretStore by name.
- **Input hardening:** catalog/server-card content is untrusted — scheme ∈ {http, https}, response bodies capped at 1 MiB, everything interpolated into shell text passes `shlex.quote()`.
- **Deadline:** 10s total wall-clock for a whole resolve (all hops/phases).
- **No bare `except Exception`.** Catch specific errors; each failure class gets a distinct one-line stderr message and non-zero exit — no tracebacks.
- **Vendored schema stays byte-identical to upstream**; provenance lives in a sidecar file.
- **Env vars:** `A2A_BASE_URL` (existing, default `http://localhost:8080`), `ARD_PUBLISHER` (new; default = hostname of `A2A_BASE_URL`).
- **Canonical test command:** `.venv/bin/pytest tests/ -x -q`. Every new test must be seen to FAIL before the implementation lands (red-first).
- Commit after every task; message style `feat(ard): …` / `test(ard): …` / `fix(cardgen): …`. Trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Commit with explicit paths: `git commit -m "…" -- <paths>` (repo hook blocks whole-index commits).

---

### Task 1: Vendor the ARD schema + provenance sidecar

**Files:**
- Create: `tests/fixtures/ai-catalog.schema.json` (byte-identical upstream copy)
- Create: `tests/fixtures/ai-catalog.schema.provenance.md`
- Test: `tests/test_ai_catalog.py` (new file, first test)

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/fixtures/ai-catalog.schema.json` — loaded by Tasks 4/5 tests via `json.load(open("tests/fixtures/ai-catalog.schema.json"))`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_catalog.py
import json
from pathlib import Path

import jsonschema

FIXTURES = Path(__file__).parent / "fixtures"


def _load_schema():
    return json.loads((FIXTURES / "ai-catalog.schema.json").read_text())


def test_vendored_schema_is_valid_draft_2020_12():
    schema = _load_schema()
    # raises if the schema itself is malformed
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["specVersion"]["enum"] == ["1.0"]


def test_provenance_sidecar_exists_and_names_source():
    text = (FIXTURES / "ai-catalog.schema.provenance.md").read_text()
    assert "ards-project/ard-spec" in text
    assert "2026-" in text  # retrieval date present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ai_catalog.py -v`
Expected: FAIL — `FileNotFoundError: ... ai-catalog.schema.json`

- [ ] **Step 3: Fetch the schema byte-identical + write the sidecar**

```bash
curl -sf https://raw.githubusercontent.com/ards-project/ard-spec/main/spec/schemas/ai-catalog.schema.json \
  -o tests/fixtures/ai-catalog.schema.json
```

```markdown
<!-- tests/fixtures/ai-catalog.schema.provenance.md -->
# Provenance: ai-catalog.schema.json

- Source: https://raw.githubusercontent.com/ards-project/ard-spec/main/spec/schemas/ai-catalog.schema.json
  (repo: github.com/ards-project/ard-spec, Apache-2.0)
- Retrieved: 2026-07-26 (record the actual date + `git -C` upstream commit if cloned)
- Rule: the JSON file stays BYTE-IDENTICAL to upstream (JSON has no comments;
  scripts/check_ard_schema_drift.py diffs raw bytes). Metadata lives HERE, never in the JSON.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ai_catalog.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/ai-catalog.schema.json tests/fixtures/ai-catalog.schema.provenance.md tests/test_ai_catalog.py
git commit -m "test(ard): vendor ai-catalog schema byte-identical + provenance sidecar

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- tests/fixtures/ai-catalog.schema.json tests/fixtures/ai-catalog.schema.provenance.md tests/test_ai_catalog.py
```

---

### Task 2: `build_mcp_server_card()` + agent-card `/a2a` fix

**Files:**
- Create: `core/cardgen/mcp_server_card.py`
- Modify: `core/cardgen/card.py` (the `"url"` value)
- Test: `tests/test_cardgen_cards.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `build_mcp_server_card(base_url: str) -> dict` with keys `name, endpoint, transport, auth`; `build_agent_card(base_url)` whose `url` == `f"{base_url}/a2a"`. Task 3 embeds the card URL; Task 5 mounts the route.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cardgen_cards.py
from core.cardgen.card import build_agent_card
from core.cardgen.mcp_server_card import build_mcp_server_card


def test_mcp_server_card_shape():
    card = build_mcp_server_card("http://reg:9113")
    assert card == {
        "name": "a2a-cli-registry",
        "endpoint": "http://reg:9113/mcp",
        "transport": "streamable-http",
        "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"},
    }


def test_agent_card_url_points_at_a2a_route():
    # Regression (spec AC-1.5): the JSON-RPC service is POST /a2a, not the base URL.
    card = build_agent_card("http://reg:9113")
    assert card["url"] == "http://reg:9113/a2a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cardgen_cards.py -v`
Expected: FAIL — `ModuleNotFoundError: core.cardgen.mcp_server_card`; second test fails with `card["url"] == "http://reg:9113"`.

- [ ] **Step 3: Implement**

```python
# core/cardgen/mcp_server_card.py
def build_mcp_server_card(base_url: str) -> dict:
    """Minimal MCP server-card document (no canonical schema exists yet —
    keep to these four fields; see spec Risk 2)."""
    return {
        "name": "a2a-cli-registry",
        "endpoint": f"{base_url}/mcp",
        "transport": "streamable-http",
        "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"},
    }
```

In `core/cardgen/card.py`, change the line `"url": base_url,` to `"url": f"{base_url}/a2a",`.

- [ ] **Step 4: Run the full suite (the card change may be asserted elsewhere)**

Run: `.venv/bin/pytest tests/ -x -q`
Expected: PASS. If an existing test pins the old `url`, update THAT assertion to `/a2a` — the old value was the bug.

- [ ] **Step 5: Commit**

```bash
git add core/cardgen/mcp_server_card.py core/cardgen/card.py tests/test_cardgen_cards.py
git commit -m "feat(cardgen): mcp-server-card builder; fix agent-card url to /a2a route

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/cardgen/mcp_server_card.py core/cardgen/card.py tests/test_cardgen_cards.py
```

---

### Task 3: `build_ai_catalog()` — schema-valid catalog builder

**Files:**
- Create: `core/cardgen/ai_catalog.py`
- Test: `tests/test_ai_catalog.py` (extend)

**Interfaces:**
- Consumes: `tests/fixtures/ai-catalog.schema.json` (Task 1).
- Produces: `build_ai_catalog(base_url: str, publisher: str) -> dict`. Task 5 routes call it; Task 6+ tests fetch its output over HTTP.

- [ ] **Step 1: Write the failing tests (append to tests/test_ai_catalog.py)**

```python
import jsonschema as _js
from core.cardgen.ai_catalog import build_ai_catalog


def test_catalog_validates_against_vendored_schema():
    cat = build_ai_catalog("http://reg:9113", publisher="reg.example.com")
    _js.validate(cat, _load_schema(),
                 format_checker=_js.Draft202012Validator.FORMAT_CHECKER)


def test_catalog_entries_reference_artifact_documents_not_endpoints():
    cat = build_ai_catalog("http://reg:9113", publisher="reg.example.com")
    urls = {e["type"]: e["url"] for e in cat["entries"]}
    # ARD §3.4: url references the artifact DOCUMENT
    assert urls["application/a2a-agent-card+json"] == "http://reg:9113/.well-known/agent-card.json"
    assert urls["application/mcp-server-card+json"] == "http://reg:9113/.well-known/mcp-server-card.json"


def test_catalog_urns_use_publisher():
    cat = build_ai_catalog("http://reg:9113", publisher="reg.example.com")
    ids = [e["identifier"] for e in cat["entries"]]
    assert ids == ["urn:air:reg.example.com:agent:catalog",
                   "urn:air:reg.example.com:mcp:server"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_ai_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: core.cardgen.ai_catalog`

- [ ] **Step 3: Implement**

```python
# core/cardgen/ai_catalog.py
def build_ai_catalog(base_url: str, publisher: str) -> dict:
    """ARD v1.0 capability manifest (reference-only, Option C).

    Entry urls point at artifact DOCUMENTS (ARD §3.4), never live endpoints.
    `publisher` should be an FQDN (ARD §4.2.1); a tailnet IP is a documented
    conformance exception (spec Risk 4).
    """
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "a2a-cli-registry",
            "documentationUrl": "https://github.com/cordsjon/a2a-cli-registry",
        },
        "entries": [
            {
                "identifier": f"urn:air:{publisher}:agent:catalog",
                "displayName": "a2a-cli-registry Agent",
                "type": "application/a2a-agent-card+json",
                "url": f"{base_url}/.well-known/agent-card.json",
                "description": "Capability-typed catalog of local CLIs (describe + plan only).",
                "tags": ["cli", "registry", "planning", "local-first"],
                "representativeQueries": [
                    "which local CLI tools are available on this machine",
                    "plan a chain of CLI tools to convert a PDF into a summary",
                    "is a given local CLI healthy right now",
                ],
            },
            {
                "identifier": f"urn:air:{publisher}:mcp:server",
                "displayName": "a2a-cli-registry MCP Server",
                "type": "application/mcp-server-card+json",
                "url": f"{base_url}/.well-known/mcp-server-card.json",
                "description": "MCP Streamable-HTTP endpoint exposing discovery + plan tools (bearer auth).",
                "tags": ["mcp", "streamable-http", "cli", "registry"],
                "representativeQueries": [
                    "list the MCP tools this registry exposes",
                    "search the local CLI fleet by capability over MCP",
                ],
            },
        ],
    }
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/pytest tests/test_ai_catalog.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/cardgen/ai_catalog.py tests/test_ai_catalog.py
git commit -m "feat(cardgen): ARD ai-catalog builder, schema-validated, artifact-document urls

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/cardgen/ai_catalog.py tests/test_ai_catalog.py
```

---

### Task 4: Serve both well-known routes

**Files:**
- Modify: `core/server/app.py` (imports + two routes next to the existing `card()` route at ~line 73)
- Test: `tests/test_ai_catalog_routes.py` (new)

**Interfaces:**
- Consumes: `build_ai_catalog`, `build_mcp_server_card` (Tasks 2-3).
- Produces: `GET /.well-known/ai-catalog.json`, `GET /.well-known/mcp-server-card.json` — both unauthenticated; env `ARD_PUBLISHER` (default: hostname of `A2A_BASE_URL`). Tasks 6-9 resolve against these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_catalog_routes.py
from fastapi.testclient import TestClient
from core.server.app import create_app


def _client(app_session_factory):
    return TestClient(create_app(app_session_factory), raise_server_exceptions=False)


def test_ai_catalog_route_no_auth(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BASE_URL", "http://reg.example.com:9113")
    monkeypatch.delenv("ARD_PUBLISHER", raising=False)
    resp = _client(app_session_factory).get("/.well-known/ai-catalog.json")
    assert resp.status_code == 200
    cat = resp.json()
    assert cat["specVersion"] == "1.0"
    # publisher defaults to the hostname of A2A_BASE_URL
    assert cat["entries"][0]["identifier"] == "urn:air:reg.example.com:agent:catalog"
    # AC-1.3: urls derive from A2A_BASE_URL
    assert cat["entries"][1]["url"] == "http://reg.example.com:9113/.well-known/mcp-server-card.json"


def test_ard_publisher_env_overrides_hostname(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BASE_URL", "http://100.92.111.112:9113")
    monkeypatch.setenv("ARD_PUBLISHER", "mini.tailnet.example")
    cat = _client(app_session_factory).get("/.well-known/ai-catalog.json").json()
    assert cat["entries"][0]["identifier"].startswith("urn:air:mini.tailnet.example:")


def test_mcp_server_card_route_no_auth(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BASE_URL", "http://reg.example.com:9113")
    resp = _client(app_session_factory).get("/.well-known/mcp-server-card.json")
    assert resp.status_code == 200
    assert resp.json()["endpoint"] == "http://reg.example.com:9113/mcp"
```

(The `app_session_factory` fixture already exists — same one `tests/test_mcp_http.py` uses.)

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_ai_catalog_routes.py -v` → 404s.

- [ ] **Step 3: Implement routes in `core/server/app.py`**

Add imports at the top (next to the `build_agent_card` import):

```python
from urllib.parse import urlparse
from core.cardgen.ai_catalog import build_ai_catalog
from core.cardgen.mcp_server_card import build_mcp_server_card
```

Add directly below the existing `card()` route:

```python
    @app.get("/.well-known/ai-catalog.json")
    def ai_catalog():
        base_url = os.environ.get("A2A_BASE_URL", "http://localhost:8080")
        publisher = os.environ.get("ARD_PUBLISHER") or (urlparse(base_url).hostname or "localhost")
        return build_ai_catalog(base_url, publisher=publisher)

    @app.get("/.well-known/mcp-server-card.json")
    def mcp_server_card():
        base_url = os.environ.get("A2A_BASE_URL", "http://localhost:8080")
        return build_mcp_server_card(base_url)
```

- [ ] **Step 4: Run full suite** — `.venv/bin/pytest tests/ -x -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add core/server/app.py tests/test_ai_catalog_routes.py
git commit -m "feat(server): serve /.well-known/ai-catalog.json + mcp-server-card.json (US-1)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/server/app.py tests/test_ai_catalog_routes.py
```

---

### Task 5: Resolver core — hardened fetch + two-hop resolution

**Files:**
- Create: `core/ard/__init__.py` (empty), `core/ard/resolve.py`
- Test: `tests/test_ard_resolve.py` (new)

**Interfaces:**
- Consumes: HTTP surface from Task 4 (in tests, monkeypatched `_fetch_json`).
- Produces:
  - `class ArdError(Exception)` — `.message` is the one-line operator message.
  - `fetch_json(url: str, deadline: float, max_bytes: int = 1_048_576) -> dict`
  - `resolve(base_url: str, type_: str, deadline_s: float = 10.0) -> str` — returns the MCP **endpoint** (for `mcp`, two hops) or the agent-card document URL (for `a2a`).
  - `TYPE_MEDIA = {"mcp": "application/mcp-server-card+json", "a2a": "application/a2a-agent-card+json"}`
  Tasks 6-8 build on these exact names.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ard_resolve.py
import json
import pytest

from core.ard import resolve as R


def _fake_fetch(payloads):
    """payloads: url -> dict | Exception. Returns a fetch_json stand-in."""
    def fetch(url, deadline, max_bytes=1_048_576):
        v = payloads[url]
        if isinstance(v, Exception):
            raise v
        return v
    return fetch


CATALOG = {
    "specVersion": "1.0",
    "entries": [
        {"identifier": "urn:air:h:agent:catalog", "displayName": "a",
         "type": "application/a2a-agent-card+json",
         "url": "http://reg:9113/.well-known/agent-card.json"},
        {"identifier": "urn:air:h:mcp:server", "displayName": "m",
         "type": "application/mcp-server-card+json",
         "url": "http://reg:9113/.well-known/mcp-server-card.json"},
    ],
}
CARD = {"name": "a2a-cli-registry", "endpoint": "http://reg:9113/mcp",
        "transport": "streamable-http", "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"}}


def test_resolve_mcp_is_two_hop(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/mcp-server-card.json": CARD,
    }))
    assert R.resolve("http://reg:9113", "mcp") == "http://reg:9113/mcp"


def test_resolve_a2a_returns_card_document_url(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch(
        {"http://reg:9113/.well-known/ai-catalog.json": CATALOG}))
    assert R.resolve("http://reg:9113", "a2a") == "http://reg:9113/.well-known/agent-card.json"


def test_no_matching_type_raises_ard_error(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch(
        {"http://reg:9113/.well-known/ai-catalog.json": {"specVersion": "1.0", "entries": []}}))
    with pytest.raises(R.ArdError, match="no entry of type"):
        R.resolve("http://reg:9113", "mcp")


def test_server_card_missing_endpoint_raises(monkeypatch):
    monkeypatch.setattr(R, "fetch_json", _fake_fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/mcp-server-card.json": {"name": "x"},
    }))
    with pytest.raises(R.ArdError, match="endpoint"):
        R.resolve("http://reg:9113", "mcp")


def test_bad_scheme_rejected():
    with pytest.raises(R.ArdError, match="scheme"):
        R.resolve("file:///etc/passwd", "mcp")


def test_oversize_body_fails_closed(tmp_path):
    # fetch_json enforces the cap itself — exercise it for real over HTTP
    import http.server, threading, functools
    class Big(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"pad":"' + b"x" * 1_200_000 + b'"}')
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Big)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        with pytest.raises(R.ArdError, match="too large"):
            R.fetch_json(f"http://127.0.0.1:{srv.server_port}/x", deadline=R._now() + 10)
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_ard_resolve.py -v` → `ModuleNotFoundError: core.ard`.

- [ ] **Step 3: Implement**

```python
# core/ard/resolve.py
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
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/pytest tests/test_ard_resolve.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ard/__init__.py core/ard/resolve.py tests/test_ard_resolve.py
git commit -m "feat(ard): stdlib two-hop resolver with scheme/size/deadline hardening

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/ard/__init__.py core/ard/resolve.py tests/test_ard_resolve.py
```

---

### Task 6: Emit formatters (claude / openworker / hermes)

**Files:**
- Create: `core/ard/emit.py`
- Test: `tests/test_ard_emit.py` (new)

**Interfaces:**
- Consumes: an already-resolved endpoint string (Task 5's `resolve`).
- Produces: `emit(fmt: str, endpoint: str) -> str` with `fmt ∈ EMIT_FORMATS = ("claude", "openworker", "hermes")`. Raises `ValueError` on unknown fmt. Task 7 wires it to the CLI.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ard_emit.py
import json
import shlex

import pytest

from core.ard.emit import emit, EMIT_FORMATS


ENDPOINT = "http://reg:9113/mcp"


def test_claude_emit_has_bearer_header_and_roundtrips_shlex():
    out = emit("claude", ENDPOINT)
    # AC-2.4: header present, env-var by NAME (consumer-side expansion)
    assert '--header "Authorization: Bearer ${A2A_BEARER_TOKEN}"' in out
    assert shlex.split(out)  # parses cleanly as shell words
    assert out.startswith("claude mcp add --transport http cli-registry ")


def test_openworker_emit_is_json_with_secretstore_ref():
    doc = json.loads(emit("openworker", ENDPOINT))
    assert doc == {"name": "cli-registry", "transport": "http",
                   "url": ENDPOINT, "auth": "secretstore:cli-registry"}


def test_hermes_emit_is_config_line():
    assert emit("hermes", ENDPOINT) == f"cli_registry_url={ENDPOINT}"


def test_no_emit_format_ever_contains_a_token_literal(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "sk-SUPERSECRET")
    for fmt in EMIT_FORMATS:
        assert "sk-SUPERSECRET" not in emit(fmt, ENDPOINT)


def test_shell_metacharacters_in_endpoint_are_quoted():
    evil = "http://reg:9113/mcp$(rm -rf ~)"
    out = emit("claude", evil)
    # AC-2.5: the url must arrive as ONE inert shell word
    assert any(w == evil for w in shlex.split(out))


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        emit("gemini", ENDPOINT)
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: core.ard.emit`.

- [ ] **Step 3: Implement**

```python
# core/ard/emit.py
"""Consumer config emit (spec US-2). Never touches tokens: snippets reference
$A2A_BEARER_TOKEN / SecretStore entries by NAME only. Everything interpolated
into shell text is shlex-quoted (catalog content is untrusted)."""
import json
import shlex

EMIT_FORMATS = ("claude", "openworker", "hermes")


def emit(fmt: str, endpoint: str) -> str:
    if fmt == "claude":
        return (
            f"claude mcp add --transport http cli-registry {shlex.quote(endpoint)} "
            f'--header "Authorization: Bearer ${{A2A_BEARER_TOKEN}}"'
        )
    if fmt == "openworker":
        return json.dumps({
            "name": "cli-registry",
            "transport": "http",
            "url": endpoint,
            "auth": "secretstore:cli-registry",
        })
    if fmt == "hermes":
        return f"cli_registry_url={endpoint}"
    raise ValueError(f"unknown emit format '{fmt}' (choose: {', '.join(EMIT_FORMATS)})")
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/pytest tests/test_ard_emit.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ard/emit.py tests/test_ard_emit.py
git commit -m "feat(ard): emit formatters with bearer refs + shlex hardening

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/ard/emit.py tests/test_ard_emit.py
```

---

### Task 7: CLI wiring — `ard-resolve` command

**Files:**
- Modify: `core/cli/main.py` (add `"ard-resolve"` to `choices`, add flags, add dispatch block)
- Test: `tests/test_cli_ard_resolve.py` (new)

**Interfaces:**
- Consumes: `core.ard.resolve.resolve`, `core.ard.resolve.ArdError`, `core.ard.emit.emit`.
- Produces: `a2a-cli-registry ard-resolve --base-url URL [--type mcp|a2a] [--emit claude|openworker|hermes]` → resolved URL or snippet on stdout, exit 0; one-line stderr + exit 1 on any `ArdError`; exit 2 on invalid flag combos.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_ard_resolve.py
import pytest

from core.cli.main import main


def test_ard_resolve_prints_endpoint(monkeypatch, capsys):
    import core.ard.resolve as R
    monkeypatch.setattr(R, "resolve", lambda base, t, deadline_s=10.0: "http://reg:9113/mcp")
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "mcp"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "http://reg:9113/mcp"


def test_ard_resolve_emit_claude(monkeypatch, capsys):
    import core.ard.resolve as R
    monkeypatch.setattr(R, "resolve", lambda base, t, deadline_s=10.0: "http://reg:9113/mcp")
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "mcp",
               "--emit", "claude"])
    assert rc == 0
    assert "claude mcp add" in capsys.readouterr().out


def test_emit_with_type_a2a_is_rejected(capsys):
    # AC-2.4: nonsense combo exits non-zero BEFORE any network I/O
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "a2a",
               "--emit", "claude"])
    assert rc == 2
    assert "only valid with --type mcp" in capsys.readouterr().err


def test_missing_base_url_is_rejected(capsys):
    rc = main(["ard-resolve"])
    assert rc == 2
    assert "--base-url" in capsys.readouterr().err


def test_ard_error_is_one_line_no_traceback(monkeypatch, capsys):
    import core.ard.resolve as R
    def boom(base, t, deadline_s=10.0):
        raise R.ArdError("GET http://reg:9113/... -> HTTP 404")
    monkeypatch.setattr(R, "resolve", boom)
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "mcp"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "HTTP 404" in err and "Traceback" not in err
```

- [ ] **Step 2: Run to verify failure** — argparse rejects `ard-resolve` (not in `choices`).

- [ ] **Step 3: Implement in `core/cli/main.py`**

Add `"ard-resolve"` to the `choices=[...]` list. Add flags after the existing ones (global-flag convention, `[ard-resolve]` help prefix):

```python
    parser.add_argument("--base-url", default="",
                        help="[ard-resolve] registry base URL to resolve against")
    parser.add_argument("--type", dest="ard_type", choices=["mcp", "a2a"], default="mcp",
                        help="[ard-resolve] artifact type to resolve")
    parser.add_argument("--emit", choices=["claude", "openworker", "hermes"], default="",
                        help="[ard-resolve] emit a consumer config snippet (mcp only)")
    parser.add_argument("--check", action="store_true",
                        help="[ard-resolve] self-check: verify own catalog entries are live")
```

Add the dispatch block BEFORE the DB-touching commands (it must not open the DB or the lock; place it right after `args, _rest = parser.parse_known_args(argv)` and the `discover` block):

```python
    if args.command == "ard-resolve":
        import core.ard.resolve as ard_resolve
        from core.ard.emit import emit as ard_emit
        if args.check:
            from core.ard.check import run_check     # Task 8
            return run_check(args.base_url or
                             os.environ.get("A2A_BASE_URL", "http://localhost:8080"))
        if not args.base_url:
            print("ard-resolve: --base-url is required", file=sys.stderr)
            return 2
        if args.emit and args.ard_type != "mcp":
            print("ard-resolve: --emit is only valid with --type mcp", file=sys.stderr)
            return 2
        try:
            resolved = ard_resolve.resolve(args.base_url, args.ard_type)
        except ard_resolve.ArdError as e:
            print(f"ard-resolve: {e}", file=sys.stderr)
            return 1
        print(ard_emit(args.emit, resolved) if args.emit else resolved)
        return 0
```

(`import sys` / `import os` already exist at module top — verify, don't duplicate. For Step 4's run, stub `core/ard/check.py` is NOT needed: `--check` isn't exercised until Task 8; the import sits inside the `if args.check:` branch.)

- [ ] **Step 4: Run to verify pass** — `.venv/bin/pytest tests/test_cli_ard_resolve.py tests/ -x -q` → PASS (full suite guards the shared-parser change against regressions in other commands).

- [ ] **Step 5: Commit**

```bash
git add core/cli/main.py tests/test_cli_ard_resolve.py
git commit -m "feat(cli): ard-resolve command — flags, emit, distinct failure exits

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/cli/main.py tests/test_cli_ard_resolve.py
```

---

### Task 8: `--check` self-health (US-7)

**Files:**
- Create: `core/ard/check.py`
- Test: `tests/test_ard_check.py` (new)

**Interfaces:**
- Consumes: `fetch_json`, `ArdError`, `TYPE_MEDIA` (Task 5); env `A2A_BEARER_TOKEN` (optional — selects the tier).
- Produces: `run_check(base_url: str) -> int` (0 all-ok / 1 any failure), printing one status line per entry: `<identifier> <ok|alive-unverified|FAIL: reason>`. Wired by Task 7's `--check` branch.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ard_check.py
import pytest

import core.ard.check as C
import core.ard.resolve as R


CATALOG = {
    "specVersion": "1.0",
    "entries": [
        {"identifier": "urn:air:h:agent:catalog", "displayName": "a",
         "type": "application/a2a-agent-card+json",
         "url": "http://reg:9113/.well-known/agent-card.json"},
        {"identifier": "urn:air:h:mcp:server", "displayName": "m",
         "type": "application/mcp-server-card+json",
         "url": "http://reg:9113/.well-known/mcp-server-card.json"},
    ],
}
AGENT_CARD = {"protocolVersion": "1.0", "name": "a2a-cli-registry",
              "url": "http://reg:9113/a2a", "skills": []}
SERVER_CARD = {"name": "a2a-cli-registry", "endpoint": "http://reg:9113/mcp",
               "transport": "streamable-http", "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"}}


def _fetch(payloads):
    def f(url, deadline, max_bytes=1_048_576):
        v = payloads[url]
        if isinstance(v, Exception):
            raise v
        return v
    return f


def test_check_all_ok_unauthenticated(monkeypatch, capsys):
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(C, "fetch_json", _fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/agent-card.json": AGENT_CARD,
        "http://reg:9113/.well-known/mcp-server-card.json": SERVER_CARD,
    }))
    # unauthenticated tier: a 401 from the endpoint counts as alive-unverified
    monkeypatch.setattr(C, "_endpoint_status", lambda ep, token: "alive-unverified")
    rc = C.run_check("http://reg:9113")
    out = capsys.readouterr().out
    assert rc == 0
    assert "urn:air:h:agent:catalog ok" in out
    assert "urn:air:h:mcp:server alive-unverified" in out


def test_check_authenticated_handshake_reports_ok(monkeypatch, capsys):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "t")
    monkeypatch.setattr(C, "fetch_json", _fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/agent-card.json": AGENT_CARD,
        "http://reg:9113/.well-known/mcp-server-card.json": SERVER_CARD,
    }))
    monkeypatch.setattr(C, "_endpoint_status", lambda ep, token: "ok")
    assert C.run_check("http://reg:9113") == 0
    assert "urn:air:h:mcp:server ok" in capsys.readouterr().out


def test_check_dead_entry_fails_and_names_it(monkeypatch, capsys):
    # AC-7.2 red-first: a wrong entry url must FAIL the check and be named
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(C, "fetch_json", _fetch({
        "http://reg:9113/.well-known/ai-catalog.json": CATALOG,
        "http://reg:9113/.well-known/agent-card.json": R.ArdError("GET ... -> HTTP 404"),
        "http://reg:9113/.well-known/mcp-server-card.json": SERVER_CARD,
    }))
    monkeypatch.setattr(C, "_endpoint_status", lambda ep, token: "alive-unverified")
    rc = C.run_check("http://reg:9113")
    out = capsys.readouterr().out
    assert rc == 1
    assert "urn:air:h:agent:catalog FAIL" in out
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: core.ard.check`.

- [ ] **Step 3: Implement**

```python
# core/ard/check.py
"""Catalog self-check (spec US-7). Pure HTTP — no DB, no lock (probe's write-lock
must NOT be contended by a read-only network check).

Two health tiers for the MCP endpoint (spec: '401 is alive' only proves the auth
gate exists): with A2A_BEARER_TOKEN -> real MCP initialize handshake ('ok');
without -> 401 counts as 'alive-unverified' (visibly weaker)."""
import json
import os
import urllib.error
import urllib.request

from core.ard.resolve import ArdError, fetch_json, _now, TYPE_MEDIA

_INIT_PAYLOAD = {
    "jsonrpc": "2.0", "method": "initialize", "id": 1,
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "ard-check", "version": "0.0.1"}},
}


def _endpoint_status(endpoint: str, token: str | None) -> str:
    """'ok' | 'alive-unverified' | raises ArdError."""
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(endpoint, method="POST", headers=headers,
                                 data=json.dumps(_INIT_PAYLOAD).encode())
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if token and resp.status == 200:
                return "ok"
            return "alive-unverified"
    except urllib.error.HTTPError as e:
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
            doc = fetch_json(entry["url"], deadline)
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
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/pytest tests/test_ard_check.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ard/check.py tests/test_ard_check.py
git commit -m "feat(ard): --check self-health, two-tier endpoint status, lock-free (US-7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/ard/check.py tests/test_ard_check.py
```

---

### Task 9: E2E — full chain catalog → card → endpoint → tools (AC-2.2)

**Files:**
- Test: `tests/test_ard_e2e.py` (new; clone-and-adapt from `tests/test_mcp_http.py` — reuse its `_parse_sse` approach and TestClient-as-context-manager rule)

**Interfaces:**
- Consumes: everything from Tasks 2-5 plus the existing MCP mount.
- Produces: the epic's "live consumer" proof. No production code — if this task needs production changes, a prior task was wrong; fix THERE.

- [ ] **Step 1: Write the E2E test (it should pass immediately if Tasks 1-8 are correct — its value is failing when any link of the chain breaks)**

```python
# tests/test_ard_e2e.py
"""AC-2.2: a consumer walks the FULL discovery chain with no hardcoded paths:
catalog -> mcp entry -> server-card -> endpoint -> MCP initialize + tools/list."""
import json

from fastapi.testclient import TestClient
from core.server.app import create_app

_TOKEN = "e2e-secret"


def _parse_sse(text):
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return out


def test_full_ard_chain_reaches_tools(app_session_factory, monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", _TOKEN)
    monkeypatch.setenv("A2A_BASE_URL", "http://testserver")

    app = create_app(app_session_factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        # hop 1: catalog (public)
        cat = client.get("/.well-known/ai-catalog.json").json()
        entry = next(e for e in cat["entries"]
                     if e["type"] == "application/mcp-server-card+json")
        # hop 2: server-card document — path taken FROM the catalog
        card_path = entry["url"].removeprefix("http://testserver")
        card = client.get(card_path).json()
        endpoint_path = card["endpoint"].removeprefix("http://testserver")
        assert endpoint_path == "/mcp"

        headers = {
            "Authorization": f"Bearer {_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        init = client.post(endpoint_path + "/", headers=headers, json={
            "jsonrpc": "2.0", "method": "initialize", "id": 1,
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "ard-e2e", "version": "0.0.1"}},
        })
        assert init.status_code == 200
        session_id = init.headers.get("mcp-session-id")
        if session_id:
            headers["mcp-session-id"] = session_id
        client.post(endpoint_path + "/", headers=headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = client.post(endpoint_path + "/", headers=headers, json={
            "jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}})
        assert listed.status_code == 200
        msgs = _parse_sse(listed.text) or [listed.json()]
        tools = next(m["result"]["tools"] for m in msgs if "result" in m)
        assert len(tools) >= 1
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/pytest tests/test_ard_e2e.py -v`
Expected: PASS. If the MCP session handshake differs (session-id header name, trailing-slash mount), align with what `tests/test_mcp_http.py` does — that file is the authority for this repo's MCP-over-TestClient mechanics.

- [ ] **Step 3: Red-proof the chain (temporarily break it)**

Edit `core/cardgen/mcp_server_card.py` endpoint to `f"{base_url}/wrong"`, run the test → must FAIL at the endpoint hop. Revert. This proves the test walks the chain rather than asserting constants.

- [ ] **Step 4: Full suite** — `.venv/bin/pytest tests/ -x -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ard_e2e.py
git commit -m "test(ard): E2E consumer proof — catalog->card->endpoint->tools/list (AC-2.2)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- tests/test_ard_e2e.py
```

---

### Task 10: Schema-drift script (US-8)

**Files:**
- Create: `scripts/check_ard_schema_drift.py`
- Test: `tests/test_ard_schema_drift.py` (new)

**Interfaces:**
- Consumes: `tests/fixtures/ai-catalog.schema.json` + `.provenance.md` (Task 1).
- Produces: `python scripts/check_ard_schema_drift.py [--vendored PATH] [--upstream-json PATH_OR_URL]` → exit 0 identical / 1 drift (prints changed top-level field paths) / 2 fetch error. Operator note: register as a weekly dagu job alongside `qmd_health_check` (registration itself is an operator step outside this repo).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ard_schema_drift.py
import json
from pathlib import Path

from scripts.check_ard_schema_drift import compare_schemas, main as drift_main

FIXTURES = Path(__file__).parent / "fixtures"


def test_identical_schemas_report_no_drift():
    doc = json.loads((FIXTURES / "ai-catalog.schema.json").read_text())
    assert compare_schemas(doc, doc) == []


def test_modified_copy_reports_changed_paths(tmp_path):
    # AC-8.1: an artificial change is detected and the changed path named
    upstream = json.loads((FIXTURES / "ai-catalog.schema.json").read_text())
    vendored = json.loads(json.dumps(upstream))
    vendored["properties"]["specVersion"]["enum"] = ["1.0", "1.1"]
    changed = compare_schemas(vendored, upstream)
    assert any("properties.specVersion" in p for p in changed)


def test_cli_exit_codes(tmp_path):
    # AC-8.2: retrieval-date visibility comes from the provenance sidecar
    up = tmp_path / "up.json"; up.write_text('{"a": 1}')
    same = tmp_path / "v.json"; same.write_text('{"a": 1}')
    diff = tmp_path / "d.json"; diff.write_text('{"a": 2}')
    assert drift_main(["--vendored", str(same), "--upstream-json", str(up)]) == 0
    assert drift_main(["--vendored", str(diff), "--upstream-json", str(up)]) == 1
```

- [ ] **Step 2: Run to verify failure** — import error (`scripts` has no `__init__.py`? then add `scripts/__init__.py` empty, or insert `sys.path` handling — match how existing tests import from `scripts/`; if none do, create `scripts/__init__.py`).

- [ ] **Step 3: Implement**

```python
# scripts/check_ard_schema_drift.py
"""US-8: detect upstream ARD schema drift vs the vendored byte-identical copy.

Exit 0 = identical; 1 = drift (changed top-level paths printed); 2 = fetch error.
Prints the vendored copy's retrieval date (from the provenance sidecar) so the
pin's age is visible (AC-8.2)."""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM_URL = ("https://raw.githubusercontent.com/ards-project/ard-spec/"
                "main/spec/schemas/ai-catalog.schema.json")
VENDORED = Path(__file__).resolve().parent.parent / "tests/fixtures/ai-catalog.schema.json"


def compare_schemas(vendored: dict, upstream: dict, prefix: str = "") -> list[str]:
    """Changed dotted paths, one level of detail past the divergence point."""
    changed = []
    keys = set(vendored) | set(upstream)
    for k in sorted(keys):
        path = f"{prefix}.{k}" if prefix else k
        if k not in vendored or k not in upstream:
            changed.append(path)
        elif isinstance(vendored[k], dict) and isinstance(upstream[k], dict):
            changed.extend(compare_schemas(vendored[k], upstream[k], path))
        elif vendored[k] != upstream[k]:
            changed.append(path)
    return changed


def _load(path_or_url: str) -> dict:
    if path_or_url.startswith(("http://", "https://")):
        with urllib.request.urlopen(path_or_url, timeout=15) as resp:
            return json.loads(resp.read(2_000_000))
    return json.loads(Path(path_or_url).read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendored", default=str(VENDORED))
    ap.add_argument("--upstream-json", default=UPSTREAM_URL)
    args = ap.parse_args(argv)
    prov = Path(args.vendored).with_name("ai-catalog.schema.provenance.md")
    if prov.exists():
        m = re.search(r"Retrieved:\s*(\S+)", prov.read_text())
        if m:
            print(f"vendored copy retrieved: {m.group(1)}")
    try:
        vendored = _load(args.vendored)
        upstream = _load(args.upstream_json)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"drift-check: fetch/parse failed: {e}", file=sys.stderr)
        return 2
    changed = compare_schemas(vendored, upstream)
    if not changed:
        print("no drift: vendored schema matches upstream")
        return 0
    print("DRIFT — changed paths:")
    for p in changed:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/pytest tests/test_ard_schema_drift.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_ard_schema_drift.py tests/test_ard_schema_drift.py
git commit -m "feat(scripts): ARD schema-drift check with provenance-age report (US-8)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- scripts/check_ard_schema_drift.py tests/test_ard_schema_drift.py
```

(If Step 2 required `scripts/__init__.py`, include it in the same commit.)

---

### Task 11: README "Discovery (ARD)" section (US-Docs)

**Files:**
- Modify: `README.md` (new `## Discovery (ARD)` section after "## What's in v1.3"; add one Quickstart line)

**Interfaces:**
- Consumes: final flag names from Task 7 (`--base-url`, `--type`, `--emit`, `--check`).
- Produces: operator docs; AC-D.1..3.

- [ ] **Step 1: Add the section**

````markdown
## Discovery (ARD)

The registry publishes an [ARD](https://github.com/ards-project/ard-spec) catalog at
`/.well-known/ai-catalog.json` referencing two artifact documents: the A2A Agent Card
and an MCP server-card (`/.well-known/mcp-server-card.json`, whose `endpoint` is the
live `/mcp` URL — two-hop resolution per ARD §3.4).

```bash
# resolve the MCP endpoint from any host serving the catalog
a2a-cli-registry ard-resolve --base-url http://127.0.0.1:9113
# → http://127.0.0.1:9113/mcp

# wire Claude Code (codex / gemini operators: same URL + transport, your config surface)
a2a-cli-registry ard-resolve --base-url http://127.0.0.1:9113 --emit claude
# → claude mcp add --transport http cli-registry http://127.0.0.1:9113/mcp --header "Authorization: Bearer ${A2A_BEARER_TOKEN}"

# self-check: are the catalog's advertised documents + endpoint actually live?
A2A_BEARER_TOKEN=… a2a-cli-registry ard-resolve --base-url http://127.0.0.1:9113 --check
```

Auth is always referenced by env-var name (`$A2A_BEARER_TOKEN`) — no command here
ever contains a token literal. Set `ARD_PUBLISHER` to your FQDN to control the
`urn:air:<publisher>:…` identifiers (defaults to the `A2A_BASE_URL` hostname).
````

Also add to the Quickstart command block: `a2a-cli-registry ard-resolve --base-url http://localhost:8080   # discover endpoints from the ARD catalog`.

- [ ] **Step 2: Verify the commands as written (AC-D.1)**

Run against a live local server (serve in one shell, resolve in another):
`A2A_BEARER_TOKEN=s .venv/bin/python -m core.cli.main serve --db demo/registry.db` then
`.venv/bin/python -m core.cli.main ard-resolve --base-url http://127.0.0.1:<port>` → prints `…/mcp`.
(If the module entrypoint differs, use the installed `a2a-cli-registry` script — whichever the Quickstart already documents.)

- [ ] **Step 3: Grep guard (AC-D.3)** — `grep -n "Bearer " README.md` shows only `${A2A_BEARER_TOKEN}` forms, no literals.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: Discovery (ARD) section — catalog, ard-resolve, wiring examples (US-Docs)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- README.md
```

---

## Final gate (after all tasks)

- [ ] `.venv/bin/pytest tests/ -q` → full suite green (canonical command, no subset claims).
- [ ] Live smoke: `serve` + `curl -s http://127.0.0.1:<port>/.well-known/ai-catalog.json | .venv/bin/python -m json.tool` → valid catalog; `ard-resolve --check` → both entries reported.
- [ ] Push `master`.
