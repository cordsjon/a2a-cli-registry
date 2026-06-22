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
### Security
- Planner now enforces fail-UNSAFE on **inferred** side-effects: a hop whose
  non-`none` `side_effect` came from inference is excluded from planned chains by
  default (matches spec §8), included only when its class is in
  `allow_side_effects`. Previously inferred side-effects were ranked lower, not
  excluded.
- Prober now enforces a real output cap (`max_output_bytes`, default 65536) via a
  bounded drain, so a runaway probed CLI cannot exhaust memory — honoring the
  SECURITY.md "output cap" claim the code did not previously implement.
- Announcer now applies the notifier's SSRF guard (blocks private/loopback
  brokers, fail-closed) and optional HMAC signing (`A2A_ANNOUNCE_SECRET`) to
  outbound broker POSTs, matching the notifier bus's protections.

### Fixed
- Input validation now type-checks values against each op's `input_schema`
  (string/integer/number/boolean/array/object; `bool` is not accepted as
  `integer`) on both the A2A and MCP surfaces — previously only key presence was
  checked. The two duplicate validators were consolidated into one.
- `serve --host/--port` now derives `A2A_BASE_URL` (when not pre-set) so the
  agent-card URL and the MCP allowed-hosts match the actual bind port; an
  explicit `A2A_BASE_URL` still wins, and `0.0.0.0` derives to `localhost`.
- `audit`/`lifecycle` no longer create an empty registry DB before exiting 2.

### Changed
- Typed input fields now reject an explicit `null` (e.g. `{"slug": null}`) with a
  type error before reaching the handler. `null` was never valid for a typed
  field; this is a stricter-but-correct validation change.

### Added
- Initial design spec (capability model, dual A2A+MCP surfaces, outcome planner).
