# a2a-cli-registry

> Point an AI agent at the CLIs already on your machine — discover them,
> see which are healthy, and get a **suggested chain of tools** to reach a goal.
> Served over both **MCP** and **A2A**. Describe + plan only (no remote execution).

**Status:** v1.0. Language-agnostic *by design*
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
a2a-cli-registry graph                                # see the computed call-graph
A2A_BEARER_TOKEN=secret a2a-cli-registry serve        # serve A2A + MCP (Streamable HTTP at /mcp)
# then point Claude Code / any MCP client at http://localhost:8080/mcp
```

> `pip install a2a-cli-registry` will work **once the package is published to PyPI**
> (not yet released — install from source above for now).

## What's in v1.0
- **Operator CLI:** `populate`, `discover`, `graph`, `serve` wired to the engine (`audit`/`lifecycle` are roadmapped — they exit 2 today).
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
