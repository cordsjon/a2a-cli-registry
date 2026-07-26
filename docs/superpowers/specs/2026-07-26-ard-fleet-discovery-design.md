# ARD Fleet Discovery — Design Spec

**Date:** 2026-07-26
**Epic:** ARD-based fleet discovery
**Status:** Draft — pending operator review
**Owning repo:** a2a-cli-registry (US-1, US-2); consumer USs land in their owning repos, tracked here.

## Problem

Every consumer of a2a-cli-registry (Hermes, OpenWorker, Claude Code, codex, gemini,
beehive hives) reaches it through a hand-wired URL — e.g. hermes-adapter's
`cli_registry_url: "http://127.0.0.1:9113/mcp/"` in `config.py`. Each new consumer
repeats that toil; remote hives can't find the registry at all without copying config.

Google + partners published **ARD (Agentic Resource Discovery)** on 2026-06-17
[web: developers.googleblog.com/announcing-the-agentic-resource-discovery-specification]:
a catalog manifest served at `/.well-known/ai-catalog.json` that *wraps* existing
discovery artifacts (A2A Agent Card, MCP endpoints) by media type + URL reference.
It layers **above** the Agent Card this repo already serves at
`/.well-known/agent-card.json` — no rewrite of `core/cardgen/card.py`.

- Spec + schema: github.com/ards-project/ard-spec — `spec/schemas/ai-catalog.schema.json`
  (JSON Schema draft 2020-12; `specVersion` enum `["1.0"]`) [verified via direct curl 2026-07-26]
- Live reference instance: `https://huggingface.co/.well-known/ai-catalog.json`
  [verified via direct curl 2026-07-26]
- Caveat: spec announced as v0.9 draft ~5 weeks ago; schema enum says `"1.0"`.
  Field churn before broad adoption is a real risk — see Risks.

## Design decision (Option C — approved)

Publish a **reference-only catalog**: two `entries[]`, each a `url` pointer to an
artifact the server already serves. No embedded `data`, no per-CLI entries, no
second source of truth.

### US-1 (a2a-cli-registry): serve the catalog

New module `core/cardgen/ai_catalog.py`, sibling and clone-shape of `card.py`:

```python
def build_ai_catalog(base_url: str) -> dict:
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "a2a-cli-registry",
            "documentationUrl": "https://github.com/cordsjon/a2a-cli-registry",
        },
        "entries": [
            {
                "identifier": "urn:air:a2a-cli-registry:agent:catalog",
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
                "identifier": "urn:air:a2a-cli-registry:mcp:server",
                "displayName": "a2a-cli-registry MCP Server",
                "type": "application/mcp-server-card+json",
                "url": f"{base_url}/mcp",
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

Route in `core/server/app.py`, cloned from the `card()` route (unauthenticated GET,
`A2A_BASE_URL` env, no DB session):

```python
@app.get("/.well-known/ai-catalog.json")
def ai_catalog():
    base_url = os.environ.get("A2A_BASE_URL", "http://localhost:8080")
    return build_ai_catalog(base_url)
```

**Acceptance criteria**

- AC-1.1: `GET /.well-known/ai-catalog.json` returns 200 with the manifest above;
  no auth required (parity with agent-card route).
- AC-1.2: The official schema file is vendored at
  `tests/fixtures/ai-catalog.schema.json` (Apache-2.0, provenance header comment
  with source URL + retrieval date) and a test validates `build_ai_catalog()`
  output against it with `jsonschema` (Draft 2020-12).
- AC-1.3: URLs in entries derive from `A2A_BASE_URL` exactly as the Agent Card
  route does — test with a non-default base URL.

**Dependency note:** `jsonschema` as **test-only** dev dependency, if not already
transitively present (check `uv.lock` first). Runtime stays dependency-free.

### US-2 (a2a-cli-registry): `ard-resolve` subcommand + E2E consumer proof

New operator CLI subcommand, sibling of `populate`/`probe`/`serve`:

```
a2a-cli-registry ard-resolve <base-url> --type {mcp|a2a} [--emit {claude|openworker|hermes}]
```

Behavior:

1. Fetch `<base-url>/.well-known/ai-catalog.json` (status-checked before `.json()`;
   non-200 or schema-missing fields → non-zero exit with a one-line error).
2. Select first entry whose `type` matches: `mcp` → `application/mcp-server-card+json`,
   `a2a` → `application/a2a-agent-card+json`. No match → non-zero exit.
3. Output:
   - no `--emit`: the entry's bare `url` on stdout (scripting-friendly).
   - `--emit claude`: `claude mcp add --transport http cli-registry <url>`
     (also serves codex/gemini operators — documented, see US-Docs).
   - `--emit openworker`: JSON snippet matching OpenWorker's `coworker/mcp/config.py`
     shape: `{"name": "cli-registry", "transport": "http", "url": "<url>"}`.
   - `--emit hermes`: the hermes-adapter config line `cli_registry_url=<url>`.

**Secrets rule:** `ard-resolve` never reads, stores, or prints tokens. Emitted
snippets reference `$A2A_BEARER_TOKEN` by env-var *name* only where the target
format needs an auth field. The catalog itself is public; only the MCP/A2A
endpoints behind it are bearer-gated.

**Acceptance criteria**

- AC-2.1: Each emit format produces the documented output against a served catalog
  (unit tests with a stub HTTP server or TestClient).
- AC-2.2 (E2E — the "live consumer" gate): a test starts the app, fetches the
  catalog **as a client** (no hardcoded `/mcp` path), resolves the MCP entry from
  catalog content, connects with the `mcp` Python client over Streamable-HTTP with
  bearer auth, and asserts `tools/list` returns ≥ 1 tool. This proves the full
  chain catalog → entry → endpoint → tools.
- AC-2.3: Fetch failures (connection refused, 404, invalid JSON, no matching type)
  each exit non-zero with a distinct one-line message; no tracebacks.

### US-3 (hermes-adapter): startup resolution via catalog

At startup, hermes-adapter attempts `GET <registry-base>/.well-known/ai-catalog.json`
and, on success, sets its effective MCP URL from the resolved
`application/mcp-server-card+json` entry. **Fail-open:** any failure (timeout,
non-200, bad schema) falls back to the existing static `cli_registry_url` and logs
one warning line — discovery must never block boot or change behavior when the
catalog is unreachable.

- AC-3.1: With the registry serving the catalog, adapter startup logs show the
  resolved-from-catalog URL and CLI-slice tools work (existing test path).
- AC-3.2: With the registry down or catalog 404, adapter boots on static config
  unchanged (regression test).
- Lands in hermes-adapter's BACKLOG.md as `US-HERMES-ARD-BOOTSTRAP-01`,
  cross-referencing this spec.

### US-4 (OpenWorker, local install): consume the registry via MCP

Wire the **local** OpenWorker install to the registry using the output of
`ard-resolve --emit openworker` (config entry added per OpenWorker's MCP server
config format; token supplied through its SecretStore, not the config file).

- AC-4.1: OpenWorker lists the registry's MCP tools in its tool inventory
  (verified in the running app).
- AC-4.2: One registry tool call (e.g. CLI search) succeeds from an OpenWorker
  session.
- Scope: local config only. No OpenWorker code changes in this US.

### US-5 (beehive): fleet-wide discovery skill

A beehive-distributed artifact (skill or config fragment, per beehive's existing
sync mechanism) so Claude Code on every hive can resolve the Mini's registry over
tailnet (`100.92.111.112:9113`) via `ard-resolve` or a direct catalog fetch —
replacing per-hive hardcoded URLs. This is the US where ARD pays for itself:
remote hives don't share this machine's config files.

- AC-5.1: On at least one non-Mini hive, a fresh session can list the registry's
  MCP tools with no hand-edited URL — bootstrap path only.
- AC-5.2: The artifact is distributed through beehive's normal sync (no manual
  copy), and documents where the bearer token comes from on each hive
  (env/secrets file — never in the synced artifact).

### US-6 (OpenWorker upstream — planned, deferred)

Contribute ARD auto-discovery to upstream OpenWorker (fetch `ai-catalog.json` →
auto-register MCP servers). **Deferral gate:** start only after (a) US-4 has run
locally for long enough to trust the shape, and (b) ARD spec churn settles
(v1.0-final or visible multi-vendor adoption). Tracked here so it isn't lost;
not part of this epic's execution scope.

### US-Docs (a2a-cli-registry)

README section "Discovery (ARD)": what the catalog endpoint is, `ard-resolve`
usage, and copy-paste wiring for Claude Code, codex, and gemini (all three take
a URL + transport; only the config surface differs).

## Sequencing

US-1 → US-2 (needs the endpoint) → US-3/US-4/US-5 in any order (all need US-2's
resolver or at least US-1's endpoint) → US-Docs alongside → US-6 deferred.

## Error handling summary

- Serve side: pure function, no I/O beyond env read — no new failure modes.
- Resolve side: status-checked fetch, distinct non-zero exits per failure class
  (AC-2.3).
- Consumer side: fail-open to existing static config everywhere (AC-3.2); a
  broken catalog must never degrade a consumer below today's behavior.

## Risks & trade-offs

1. **Spec churn (highest):** ARD is weeks old. Mitigation: reference-only entries
   (small surface), vendored schema pinned with provenance, `trustManifest`
   omitted, US-6 deferred behind a maturity gate.
2. **Media-type semantics:** the MCP entry's `url` points at the live `/mcp`
   protocol endpoint while `type` says `…server-card+json` (a card document).
   This matches observed ecosystem practice (Hugging Face's live catalog points
   its entry at a service base URL) but could shift; flagged for re-check at
   spec v1.0.
3. **Static catalog:** entries and `representativeQueries` are constants, not
   DB-derived — they describe the registry, not individual CLIs. Per-CLI ARD
   entries (Option B) remain possible later without breaking Option C consumers.
4. **URN publisher naming:** `urn:air:a2a-cli-registry:…` uses the project name,
   not a domain. Fine for self-hosted/tailnet use; revisit only if the catalog
   is ever published to a public directory.

## Out of scope

- `trustManifest` / signing / attestations (spec too young; real new surface).
- Per-CLI catalog entries (Option B).
- Consuming *other* hosts' ARD catalogs into the registry DB.
- Any upstream OpenWorker code change (deferred to US-6).
