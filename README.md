# a2a-cli-registry

> Point an AI agent at the CLIs already on your machine — discover them,
> see which are healthy, and get a **suggested chain of tools** to reach a goal.
> Served over both **MCP** and **A2A**. Describe + plan only (no remote execution).

**Status:** v1 ships a **Python** tool adapter. Language-agnostic *by design*
(Go/Node/shell adapters are stubs — non-Python tools work today by *declaring*
their capabilities). Targets **A2A v1.0** and the **official MCP SDK** (exact
pinned versions in the design spec + `SECURITY.md`). Apache-2.0. **Pre-1.0:
surfaces may change.**

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

## Status of the surfaces (read before you try it)

v1 is **library-first**. The engine — discover → populate → compute call-graph →
plan a tool chain → serve over A2A + MCP — is complete and covered end-to-end by
the test suite. The **operator CLI is not wired yet**: only `graph` runs from the
command line; `populate`/`discover`/`audit`/`lifecycle` exit non-zero with
"not implemented in v1" rather than pretend to work. Drive the pipeline through
the library API until the CLI lands (tracked for a follow-up release).

## Quickstart (library API)
```bash
pip install -e .                        # no PyPI release yet; install from source
python -m pytest -q                     # 89 passing — confirms your env is good
```
```python
# Minimal end-to-end (see tests/test_e2e.py for the full version):
from core.populate import populate
from core.catalog import queries
from core.discovery.cli_audit_source import CliAuditSource
from core.adapters.python_adapter import PythonAdapter
from core.vocabulary import VocabularyRegistry

# ... open a session, build a VocabularyRegistry of your registered port types ...
populate(session, CliAuditSource("path/to/fleet.json"), [PythonAdapter()], vocab, clock)
chains = queries.plan_cli_chain(session, ["file:pdf"], ["text:summary"], [])
# -> [{"slugs": ["pdf2text", "summarize"], ...}]
```
The call-graph is also viewable from the CLI today:
```bash
python -m core.cli.main graph --db registry.db
```

## Roadmap to a wired CLI / v1.0
- `populate`/`serve`/`probe` subcommands wired to the engine (today: library API only)
- MCP served over Streamable HTTP (today: in-process tool calls)
- Python **capability inference** (today: declared capabilities only)
- PyPI release with an `a2a-cli-registry` console entry point

## Demo
> _Planned: asciinema of `plan-cli-chain file:pdf → text:summary` returning
> `[pdf2text, summarize]` — the marquee feature is visual._

## Docs
Design spec: `docs/superpowers/specs/2026-06-21-a2a-cli-registry-design.md`.
Security: `SECURITY.md`. Contributing (incl. adding a language adapter):
`CONTRIBUTING.md`.
