# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
[SemVer](https://semver.org/). Pre-1.0: minor versions may break surfaces.

## [1.0.0] - 2026-06-22
### Added
- Operator CLI wired: `populate`, `discover`, `graph`, `serve` subcommands connected to the engine (`audit`/`lifecycle` roadmapped, exit 2 today).
- MCP served over Streamable HTTP at `/mcp` behind bearer auth (same token as A2A surface).
- Python capability inference from `--help` text behind a §9 precision/recall floor; declared capabilities always win when present.
- `mcp` pinned to `1.28.0` (Streamable HTTP support).
- PyPI packaging via hatchling with `a2a-cli-registry` console entry point.
- Version bumped to 1.0.0.

## [Unreleased]
### Added
- Initial design spec (capability model, dual A2A+MCP surfaces, outcome planner).
