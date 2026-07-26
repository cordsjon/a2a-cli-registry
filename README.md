# a2a-cli-registry

> Point an AI agent at the CLIs already on your machine — discover them,
> see which are healthy, and get a **suggested chain of tools** to reach a goal.
> Served over both **MCP** and **A2A**. Describe + plan only (no remote execution).

**Status:** v1.3. Language-agnostic *by design*
(Go/Node/shell adapters are stubs — non-Python tools work today by *declaring*
their capabilities). Targets **A2A v1.0** and **`mcp==1.28.0`** (exact
pinned versions in the design spec + `SECURITY.md`). Apache-2.0.

## Who this is for
A developer/team with ~10+ local CLIs who wants an AI coding agent (Claude Code,
Copilot, any MCP/A2A client) to *find* those tools and *reason about chaining*
them — instead of re-describing the toolbox every session.

## Isn't this just an MCP registry?
No — those catalog *remote servers to install*. This catalogs the **local tools you
already have**, health-tracks them, and type-chains them:

| | local fleet | health-tracked | typed chaining | dual A2A+MCP |
|---|---|---|---|---|
| Smithery / mcp.so / Glama / official MCP registry | ✗ remote | ✗ | ✗ | MCP only |
| LangChain tool registries | n/a in-app | ✗ | ✗ | neither |
| **a2a-cli-registry** | **✓** | **✓** | **✓** | **✓** |

## Quickstart

```bash
# Not yet on PyPI — install from source:
pip install git+https://github.com/cordsjon/a2a-cli-registry
# or, from a clone:  pip install -e .

a2a-cli-registry populate --config your-config.toml   # discover + index your fleet
a2a-cli-registry probe                                # run health sweep, write per-CLI health_status
a2a-cli-registry overview                             # read-only rich view of catalog, CLIs, capabilities, health
a2a-cli-registry okf-produce --out ./bundle           # export catalog as an OKF bundle (Markdown+YAML)
a2a-cli-registry okf-ingest  --bundle ./bundle        # round-trip enriched descriptions back (descriptions only)
a2a-cli-registry graph                                # see the computed call-graph
A2A_BEARER_TOKEN=secret a2a-cli-registry serve        # serve A2A + MCP (Streamable HTTP at /mcp)
a2a-cli-registry ard-resolve --base-url http://localhost:8080   # discover endpoints from the ARD catalog
# then browse http://localhost:8080/overview or point Claude Code / any MCP client at http://localhost:8080/mcp
```

> `pip install a2a-cli-registry` will work **once the package is published to PyPI**
> (not yet released — install from source above for now).

## Configuration
The config file (`--config`, see `examples/reference-fleet/config.toml`) has two
zones. **Live** keys are read today and change behavior:

| Key | Effect |
|---|---|
| `cli_audit_path` | path to your cli-audit JSON export |
| `[vocabulary] registered` / `[vocabulary.aliases]` | the registered port vocabulary + aliases |
| `[thresholds] mass_removal` | `populate` fails closed if ≥ this fraction of CLIs would be removed |
| `[probe] probe_timeout` | per-CLI wall-time budget for health check (seconds); CLI probed longer times out |
| `[probe] max_probe_output_bytes` | captured output cap per probe (bytes); exceeding this cap prevents OOM |
| `[probe] probe_concurrency` | number of parallel health probes |
| `[probe] staleness_ttl` | time (seconds) before an unprobeable CLI's health becomes `stale`; affects agent-visible health |

Keys under a **reserved** section are parsed but not yet consumed. The planner keys await their `plan` command. Editing a reserved key has no effect until then.

## Health States
When a CLI is probed or previously probed, its health is recorded in one of four canonical states:

| State | Meaning | Recommended Agent Action |
|---|---|---|
| `healthy` | Probe succeeded (health_cmd exited 0) | Safe to plan and use |
| `unhealthy` | Probe ran but failed (non-zero exit, timeout, or crash) | Avoid; flag for operator attention |
| `stale` | Unprobeable CLI (no `health_cmd`) older than `staleness_ttl` | Treat as uncertain; no health signal available |
| `unknown` | Never probed OR unprobeable and within `staleness_ttl` | Run `probe` to establish health |

Note: `stale` applies only to unprobeable CLIs (no `health_cmd`). `unknown` applies to any CLI not yet probed, plus unprobeable CLIs whose last record is within `staleness_ttl`. `healthy` and `unhealthy` come from actual probes.

## What's in v1.3
- **OKF export:** `okf-produce --out <dir>` exports the catalog as an Open Knowledge Format bundle (Markdown + YAML); byte-stable re-produce, typed ports, call-graph edges in frontmatter.
- **OKF ingest:** `okf-ingest --bundle <dir>` round-trips LLM/human-enriched descriptions from an OKF bundle back into the catalog (descriptions only).

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
# → urn:air:127.0.0.1:agent:catalog ok
# → urn:air:127.0.0.1:mcp:server ok
```

`--check` grades the MCP endpoint in two tiers: with `A2A_BEARER_TOKEN` set it performs a
real MCP `initialize` handshake and reports `ok`; without a token a `401` only proves the
auth gate is alive, reported as the visibly weaker `alive-unverified`. Exit code is `1` if
any advertised document or endpoint is dead.

Other emit targets: `--emit openworker` (JSON config object) and `--emit hermes`
(`cli_registry_url=…`). Use `--type a2a` to resolve the Agent Card document URL instead of
the MCP endpoint.

Auth is always referenced by env-var name (`$A2A_BEARER_TOKEN`) — no command here
ever contains a token literal. Set `ARD_PUBLISHER` to your FQDN to control the
`urn:air:<publisher>:…` identifiers (defaults to the `A2A_BASE_URL` hostname).

## What's in v1.2
- **Web overview:** `GET /overview` serves an open, read-only Swagger-style HTML view with fleet totals, project buckets, filtering, health badges, capabilities, and incident edges. It does not render `launch_spec`.

## What's in v1.1
- **Operator CLI:** `populate`, `discover`, `probe`, `overview`, `graph`, `serve` wired to the engine.
- **Health tracking:** `probe` runs config-driven one-shot health sweep with timeout + SIGKILL + output cap; writes per-CLI `health_status`. `overview` renders the catalog with health badges via `rich`.
- **Plan annotations:** planner hops now carry per-hop `health_status` for agent observability (ranking unchanged).
- **Live config:** the `[probe]` table (`probe_timeout`, `max_probe_output_bytes`, `probe_concurrency`, `staleness_ttl`) is now live — editing these keys changes runtime behavior.
- **MCP over Streamable HTTP** at `/mcp`, same bearer auth as A2A.
- **Python capability inference** from `--help` text (declared still always wins), held to a measured precision/recall floor.
- Apache-2.0. Tracks A2A v1.0 + `mcp==1.28.0`.

## Demo
> _Planned: asciinema of `plan-cli-chain file:pdf → text:summary` returning
> `[pdf2text, summarize]` — the marquee feature is visual._

## Docs
Design spec: `docs/superpowers/specs/2026-06-21-a2a-cli-registry-design.md`.
Security: `SECURITY.md`. Contributing (incl. adding a language adapter):
`CONTRIBUTING.md`.
