# a2a-cli-registry

> Point an AI agent at the CLIs already on your machine — discover them,
> see which are healthy, and get a **suggested chain of tools** to reach a goal.
> Served over both **MCP** and **A2A**. Describe + plan only (no remote execution).

**Status:** v1 ships a **Python** tool adapter. Language-agnostic *by design*
(Go/Node/shell adapters are stubs — non-Python tools work today by *declaring*
their capabilities). Tracks **A2A ≥ `<tag>`** / **MCP rev `<date>`** (see SECURITY
+ design spec). Apache-2.0. **Pre-1.0: surfaces may change.**

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
pip install a2a-cli-registry            # or: pip install -e .
a2a-cli-registry populate --source filesystem --path ~/bin
a2a-cli-registry graph                  # see the computed call-graph
# then point Claude Code / any MCP client at the MCP endpoint
```

## Demo
> _TODO at v0.1: asciinema of `plan-cli-chain file:pdf → text:summary` returning
> `[pdf2text, summarize]`._ (The marquee feature is visual — show it.)

## Docs
Design spec: `docs/superpowers/specs/2026-06-21-a2a-cli-registry-design.md`.
Security: `SECURITY.md`. Contributing (incl. adding a language adapter):
`CONTRIBUTING.md`.
