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

**Entry URLs point at artifact documents, not live endpoints (codex gate, verified
ARD §3.4):** ARD's Strict Value-or-Reference rule defines `url` as "a remote
reference to the artifact document." Pointing the MCP entry at the live `/mcp`
protocol endpoint (as originally drafted, and as Risk 2 hedged) violates that
contract — a conforming client GETs the URL expecting a JSON document and gets a
protocol endpoint instead. Fix: serve a minimal **MCP server-card document** at
`/.well-known/mcp-server-card.json` (same pure-function pattern):

```python
def build_mcp_server_card(base_url: str) -> dict:
    return {
        "name": "a2a-cli-registry",
        "endpoint": f"{base_url}/mcp",
        "transport": "streamable-http",
        "auth": {"type": "bearer", "env": "A2A_BEARER_TOKEN"},
    }
```

There is no finalized standard for this card's shape yet — keep it to these four
documented fields and revisit when the media type gets a canonical schema.
Consumers (US-2 resolver, US-3) fetch the card and read `endpoint` from it —
two-hop resolution, per the ARD contract.

**URN publisher must be an FQDN (codex gate, verified ARD §4.2.1):** the spec text
requires `<publisher>` to be "a fully qualified domain name." `a2a-cli-registry`
is not one. `publisher` therefore comes from the `ARD_PUBLISHER` env var,
defaulting to the hostname of `A2A_BASE_URL`. On the tailnet that yields an IP
literal — still not an FQDN, a **documented conformance exception** acceptable
only because this catalog is never published off-tailnet (Out of scope). If that
ever changes, a real domain is the prerequisite.

**Pre-existing Agent Card bug (fix-what-you-find):** `build_agent_card()` sets
`"url": base_url`, but the A2A JSON-RPC service actually lives at `POST /a2a` —
an A2A client following the card today would call the wrong path. Fix in this US:
`"url": f"{base_url}/a2a"`, with a regression test.

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
  `tests/fixtures/ai-catalog.schema.json` **byte-identical to upstream** — JSON
  has no comments, so provenance (source URL + retrieval date + upstream commit)
  goes in a sidecar `tests/fixtures/ai-catalog.schema.provenance.md`. Keeping the
  vendored copy byte-identical is also what keeps US-8's upstream diff clean.
  A test validates `build_ai_catalog()` output against it with `jsonschema`
  (Draft 2020-12).
- AC-1.3: URLs in entries derive from `A2A_BASE_URL` exactly as the Agent Card
  route does — test with a non-default base URL.
- AC-1.4: `GET /.well-known/mcp-server-card.json` returns 200 with the four-field
  card; the catalog's MCP entry `url` points at it (not at `/mcp`).
- AC-1.5: `build_agent_card()` regression: card `url` ends in `/a2a` and a test
  asserts the card's URL path matches the mounted A2A route.

**Dependency note (resolved):** `jsonschema>=4.0` is **already declared** in
`pyproject.toml` `[project.optional-dependencies] dev` and present in `uv.lock`
(4.26.0 importable in `.venv` — verified 2026-07-26). No new dependency, no
approval needed. `tests/fixtures/` already exists.

### US-2 (a2a-cli-registry): `ard-resolve` subcommand + E2E consumer proof

```
a2a-cli-registry ard-resolve --base-url <url> --type {mcp|a2a} [--emit {claude|openworker|hermes}]
```

**CLI-shape constraint (verified `core/cli/main.py:91-121`):** this CLI does *not*
use argparse subparsers. It has ONE positional `command` with a `choices=[...]`
list plus shared global flags parsed via `parse_known_args`. Consequences the
implementation MUST respect:

- `ard-resolve` is added to the `choices` list — it cannot take its own positional
  argument, because the parser has no second positional slot. The base URL is
  therefore a **flag** (`--base-url`), not a positional as originally drafted.
- New flags (`--base-url`, `--type`, `--emit`) become globally visible in
  `--help`, like the existing `[serve]` / `[remediate]` flags. Follow the
  established convention: prefix each help string with `[ard-resolve]`.
- Do **not** migrate the CLI to subparsers as part of this epic — that is an
  unrelated refactor touching every existing command (out of scope; file
  separately if wanted).

Behavior:

1. Fetch `<base-url>/.well-known/ai-catalog.json` (status-checked before `.json()`;
   non-200 or schema-missing fields → non-zero exit with a one-line error).
   **Deadline: 10s total wall-clock for the whole resolve** (both hops, all
   phases — DNS, connect, read, redirects), not a per-phase connect/read value;
   a per-phase 5s can stall a boot path for far longer than 5s.
2. Select first entry whose `type` matches: `mcp` → `application/mcp-server-card+json`,
   `a2a` → `application/a2a-agent-card+json`. No match → non-zero exit. More than
   one match → first wins, warn on stderr.
3. **Second hop (MCP only, per ARD §3.4):** the entry's `url` is the *server-card
   document*, not the endpoint. Fetch it, read `endpoint` — that is the MCP URL.
   For `--type a2a` the entry's `url` (the Agent Card document) is itself the
   deliverable.
4. Output:
   - no `--emit`: the resolved URL on stdout (endpoint for mcp, card URL for a2a).
   - `--emit claude`:
     `claude mcp add --transport http cli-registry <endpoint> --header "Authorization: Bearer ${A2A_BEARER_TOKEN}"`
     — **without the header the generated command dials a bearer-gated endpoint
     unauthenticated and gets 401**; the env var expands on the consumer side,
     never here. (Also serves codex/gemini operators — documented, see US-Docs.)
   - `--emit openworker`: JSON snippet matching OpenWorker's `coworker/mcp/config.py`
     shape, including its auth field referencing the SecretStore entry by *name*:
     `{"name": "cli-registry", "transport": "http", "url": "<endpoint>", "auth": "secretstore:cli-registry"}` —
     exact key names to be matched against OpenWorker's config schema at
     implementation time, with the invariant: a token literal never appears.
   - `--emit hermes`: the hermes-adapter config line `cli_registry_url=<endpoint>`
     (token resolution stays in the adapter's existing `A2A_BEARER_TOKEN` chain).
   - `--emit` is **only valid with `--type mcp`** — combining it with `--type a2a`
     would emit an MCP consumer config pointing at an Agent Card document; the
     combination exits non-zero with a one-line error.

**Input hardening (catalog content is untrusted input):** before any URL from the
catalog or server-card is used or emitted: scheme must be `http` or `https`;
response bodies are capped (1 MiB) before parsing; and every value interpolated
into emitted shell text passes `shlex.quote()` — a malicious catalog must not be
able to inject shell syntax through an emit snippet.

**Secrets rule:** `ard-resolve` never reads, stores, or prints tokens. Emitted
snippets reference `$A2A_BEARER_TOKEN` / SecretStore entries by *name* only.
The catalog itself is public; only the MCP/A2A endpoints behind it are
bearer-gated.

**Acceptance criteria**

- AC-2.1: Each emit format produces the documented output against a served catalog
  (unit tests with a stub HTTP server or TestClient).
- AC-2.2 (E2E — the "live consumer" gate): a test starts the app, fetches the
  catalog **as a client** (no hardcoded paths), resolves the MCP entry, fetches
  the server-card from the entry's `url`, reads `endpoint` from it, connects with
  the `mcp` Python client over Streamable-HTTP with bearer auth, and asserts
  `tools/list` returns ≥ 1 tool. This proves the full chain
  catalog → entry → server-card → endpoint → tools.
- AC-2.3: Fetch failures (connection refused, 404, invalid JSON, no matching type,
  missing `endpoint` in server-card) each exit non-zero with a distinct one-line
  message; no tracebacks.
- AC-2.4: `--emit` with `--type a2a` exits non-zero. Emitted claude snippet
  contains the `Authorization: Bearer ${A2A_BEARER_TOKEN}` header; no emit format
  ever contains a token literal (test greps output against the env value).
- AC-2.5: Hardening tests: a catalog URL with scheme `file://`, a URL containing
  `$(...)` / backticks / quotes, and a >1 MiB body each fail closed with a
  one-line error; emitted shell text round-trips through `shlex.split` intact.

### US-3 (hermes-adapter): startup resolution via catalog

At startup, hermes-adapter attempts `GET <registry-base>/.well-known/ai-catalog.json`
and, on success, resolves the `application/mcp-server-card+json` entry, fetches
the server-card document from its `url`, and sets its effective MCP URL from the
card's `endpoint` field (same two-hop contract as US-2). **Fail-open:** any failure (timeout,
non-200, bad schema) falls back to the existing static `cli_registry_url` and logs
one warning line — discovery must never block boot or change behavior when the
catalog is unreachable.

**Host-pinning (resolves silent-redirect risk):** a resolved URL is adopted only if
its **host:port matches the configured registry base** the adapter already trusts
(ports normalized before compare: explicit `:80`/`:443` equals the scheme
default). A catalog that resolves to a *different* host is REJECTED — adapter
keeps static config and logs an error naming both URLs. Rationale: fail-open on
unreachable is safe (degrades to today's behavior), but silently following a
redirect to an unexpected host is a privilege change, not a degradation.

**Scheme rule (codex gate):** *path* changes on the pinned host are the
legitimate use (`/mcp` moving) and are accepted. Scheme changes are asymmetric:
`http → https` upgrade is accepted; **`https → http` downgrade is REJECTED** even
on the same host:port — a downgraded URL would carry the bearer token in
cleartext, which is a credential exposure, not a path move. The pinning applies
to the **final resolved endpoint** (after the server-card hop), not only the
catalog URL.

- AC-3.1: With the registry serving the catalog, adapter startup logs show the
  resolved-from-catalog URL and CLI-slice tools work (existing test path).
- AC-3.2: With the registry down or catalog 404, adapter boots on static config
  unchanged (regression test).
- AC-3.3: With a catalog whose MCP entry points at a *different host*, the adapter
  rejects it, boots on static config, and logs an error naming both URLs
  (negative test — this is the spoofed-catalog case).
- Lands in hermes-adapter's BACKLOG.md as `US-HERMES-ARD-BOOTSTRAP-01`,
  cross-referencing this spec.

### US-4 (OpenWorker, local install): consume the registry via MCP

Wire the **local** OpenWorker install to the registry using the output of
`ard-resolve --emit openworker` (config entry added per OpenWorker's MCP server
config format; token supplied through its SecretStore, not the config file).

- AC-4.1: OpenWorker lists the registry's MCP tools in its tool inventory.
  **Evidence required:** screenshot or copied tool list naming ≥ 1 registry tool,
  pasted into the US on close.
- AC-4.2: One registry tool call (e.g. CLI search) succeeds from an OpenWorker
  session. **Evidence required:** the session transcript excerpt showing the call
  and its result.
- AC-4.3: The config entry contains no token literal — the bearer comes from
  OpenWorker's SecretStore. Verified by grepping the written config file for the
  token value and finding no match.
- Scope: local config only. No OpenWorker code changes in this US.

**Manual-verification note:** US-4 and US-5 are the only USs whose ACs cannot run
in CI (they need the OpenWorker app and physical hives). Their evidence is
operator-pasted, not automated — stated plainly so nobody later mistakes them for
test-covered.

### US-5 (beehive): fleet-wide discovery skill

A beehive-distributed artifact (skill or config fragment, per beehive's existing
sync mechanism) so Claude Code on every hive can resolve the Mini's registry over
tailnet (`100.92.111.112:9113`) via `ard-resolve` or a direct catalog fetch —
replacing per-hive hardcoded URLs. This is the US where ARD pays for itself:
remote hives don't share this machine's config files.

**Trust boundary (compensating control for omitted `trustManifest`):** the catalog
is fetched over **plain HTTP on the tailnet**, so its integrity rests entirely on
Tailscale's authenticated WireGuard transport — there is no signature on the
document itself. This is acceptable only because the tailnet is the trust boundary.
Two rules follow, and both are acceptance criteria:

- The synced artifact **pins the expected host** (`100.92.111.112`) rather than
  accepting an arbitrary base URL, so a rogue catalog elsewhere cannot enroll a hive.
- A hive must **never** fetch a catalog from outside the tailnet and act on it.
  Public-internet ARD consumption stays out of scope until `trustManifest`
  verification exists (see Risks 1 and 5).

- AC-5.1: On at least one non-Mini hive, a fresh session can list the registry's
  MCP tools with no hand-edited URL — bootstrap path only.
- AC-5.2: The artifact is distributed through beehive's normal sync (no manual
  copy), and documents where the bearer token comes from on each hive
  (env/secrets file — never in the synced artifact).
- AC-5.3: The artifact pins the tailnet host; a catalog served from any other host
  is not adopted (mirrors AC-3.3's rejection rule), and the pin is enforced on the
  **final resolved endpoint** too — a pinned-host catalog whose server-card
  `endpoint` points off-tailnet is rejected the same way.

### US-7 (a2a-cli-registry): catalog self-check

Add `ard-resolve --check`: fetch own `/.well-known/ai-catalog.json`, then for each
entry assert its `url` is reachable and returns the expected shape (agent-card
entry → valid Agent Card JSON; MCP entry → server-card document with an `endpoint`
field, then the endpoint itself). Endpoint liveness has two tiers (codex gate —
"any 401 is alive" only proves the auth gate exists, not that an MCP server is
behind it):

- **Authenticated (default when `A2A_BEARER_TOKEN` is set):** perform an MCP
  initialize handshake with the token; healthy = handshake completes.
- **Unauthenticated (fallback):** 401-without-token counts as alive, and the
  report labels that entry's status `alive-unverified` — visibly weaker, so a
  wrong-but-gated path can't masquerade as verified health.

**Not a `probe` extension (verified `core/cli/main.py:286-300`):** `probe` acquires
the sidecar DB write-lock (`with_file_lock(_db_lock_path)`) and opens a session to
persist `health_status`. The catalog check is pure HTTP against the server's own
endpoints and touches no DB rows — folding it into `probe` would make a read-only
network check contend for the write-lock against a concurrent `populate`, and
would couple catalog health to DB availability. Keep it lock-free and DB-free
under `ard-resolve`.

Rationale: without this, AC-2.2 proves the chain worked *once at test time*. In
production `A2A_BASE_URL` can change, `/mcp` can move, and the catalog keeps
advertising stale URLs to every consumer with no signal. The registry already owns
health-checking as a concept (`probe`, `health_status`) — the catalog should not be
the one thing that is never probed.

- AC-7.1: With the server running, the check reports both entries reachable.
- AC-7.2: With an entry URL made wrong (e.g. bad `A2A_BASE_URL`), the check exits
  non-zero and names the failing entry — verified red before green.

### US-8 (a2a-cli-registry): upstream schema-drift detection

A scheduled check (dagu job or `qmd_health_check`-style weekly gate) fetches the
upstream `ai-catalog.schema.json`, diffs it against the vendored
`tests/fixtures/ai-catalog.schema.json`, and alerts on change. ARD is v0.9 with
admitted churn (Risk 1); a silently-diverging vendored copy means the validation
test keeps passing while the catalog drifts out of conformance with the live spec.

- AC-8.1: Given an artificially modified vendored copy, the check detects the
  difference and reports the changed field paths.
- AC-8.2: The check records the upstream retrieval date so the pin's age is visible.

### US-Docs (a2a-cli-registry)

README section "Discovery (ARD)": what the catalog endpoint is, `ard-resolve`
usage, and copy-paste wiring for Claude Code, codex, and gemini (all three take
a URL + transport; only the config surface differs).

- AC-D.1: The README section includes at least one worked example whose commands
  run as written against a local server (copy-paste verified, not hand-typed
  approximations).
- AC-D.2: The "What's in vX" list and the Quickstart command block both mention
  the catalog endpoint, matching how existing features are documented there.
- AC-D.3: No token literals appear in any documented command — auth is shown as
  `$A2A_BEARER_TOKEN`.

### US-6 (OpenWorker upstream — planned, deferred)

Contribute ARD auto-discovery to upstream OpenWorker (fetch `ai-catalog.json` →
auto-register MCP servers). **Deferral gate:** start only after (a) US-4 has run
locally for long enough to trust the shape, and (b) ARD spec churn settles
(v1.0-final or visible multi-vendor adoption). Tracked here so it isn't lost;
not part of this epic's execution scope.

## Sequencing

Strict order, no "any order" ambiguity:

1. **US-1** — serve the catalog (everything else reads it).
2. **US-2** — `ard-resolve` + E2E proof (needs the endpoint).
3. **US-7** — catalog self-check (ships with `ard-resolve`; must precede any
   remote consumer so hives are never the first to discover a stale catalog).
4. **US-3**, **US-4** — Hermes and local OpenWorker, either order, both
   independent of each other.
5. **US-5** — beehive fleet rollout (last consumer: highest blast radius,
   depends on US-7's check existing).
6. **US-8**, **US-Docs** — run alongside any of steps 2-5, no ordering constraint.
7. **US-6** — deferred behind its gate; not in this epic's execution scope.

## Error handling summary

- Serve side: pure function, no I/O beyond env read — no new failure modes.
- Resolve side: status-checked fetch with a 5s timeout, distinct non-zero exits
  per failure class (AC-2.3). No bare `except Exception`; catch the specific
  network/JSON errors and map each to its own message.
- Consumer side: fail-open to existing static config everywhere (AC-3.2), except
  host-mismatch which fails *closed* (AC-3.3) — a broken catalog must never
  degrade a consumer below today's behavior, and must never silently upgrade one
  to a new host.

**Observability:** every consumer-side resolution outcome emits exactly one log
line naming which path was taken — `resolved-from-catalog <url>`,
`fallback-static <url> (<reason>)`, or `rejected-host-mismatch <catalog-url> vs
<configured-host>`. Without this, a silently-failing-open adapter looks identical
to a working one, and the fallback becomes undetectable in production.

## Risks & trade-offs

1. **Spec churn (highest):** ARD is weeks old. Mitigation: reference-only entries
   (small surface), vendored schema pinned with provenance sidecar,
   `trustManifest` omitted, US-6 deferred behind a maturity gate.
2. **RESOLVED (codex gate) — media-type semantics:** the original draft pointed
   the MCP entry's `url` at the live `/mcp` endpoint; ARD §3.4 requires `url` to
   reference the artifact *document*. Fixed via the served
   `mcp-server-card.json` + two-hop resolution. Residual risk: the server-card's
   field shape has no canonical schema yet — four minimal fields, revisit when
   the media type standardizes.
3. **Static catalog:** entries and `representativeQueries` are constants, not
   DB-derived — they describe the registry, not individual CLIs. Per-CLI ARD
   entries (Option B) remain possible later without breaking Option C consumers.
4. **URN publisher conformance boundary:** ARD §4.2.1 requires an FQDN publisher.
   `ARD_PUBLISHER` / base-URL hostname yields an IP literal on the tailnet —
   still nonconforming, accepted only because off-tailnet publication is out of
   scope. A real domain is the prerequisite for any public directory listing.
7. **Origin discovery is NOT solved (codex gate, honesty):** every consumer still
   receives the registry's base URL from configuration (pinned artifact, static
   config, operator command). What ARD buys here is *endpoint/path* discovery,
   config *generation*, and drift *detection* behind a known origin — not
   zero-config bootstrap. The Problem section's "remote hives can't find the
   registry" is solved by the *synced pinned artifact*, with ARD resolving the
   rest; stated so nobody mistakes this for DNS-SD.
5. **No document-level integrity (accepted, bounded):** with `trustManifest`
   omitted, catalog authenticity rests on transport only — tailnet WireGuard for
   hives, loopback for the Mini. Compensating controls: host-pinning on every
   consumer (AC-3.3, AC-5.3) and a hard rule against consuming off-tailnet
   catalogs. This is the risk that most warrants revisiting at ARD v1.0; a signed
   catalog would let us drop the pinning rule rather than keep layering on it.
6. **`representativeQueries` are unmeasured:** hand-written strings whose retrieval
   value is asserted, not tested — no consumer in this repo reads them today
   (verified: no semantic/embedding consumer in `core/`). They are cheap and
   spec-conformant, so they ship, but no claim is made that they improve discovery
   until some consumer actually indexes them.

## Out of scope

- `trustManifest` / signing / attestations (spec too young; real new surface) —
  see Risk 5 for the compensating controls that make this acceptable.
- Consuming ARD catalogs from outside the tailnet (blocked until Risk 5 is closed).
- Per-CLI catalog entries (Option B).
- Consuming *other* hosts' ARD catalogs into the registry DB.
- Any upstream OpenWorker code change (deferred to US-6).
