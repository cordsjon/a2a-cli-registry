# `probe` + `overview` Commands — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorming) — ready for implementation plan
**Repo:** a2a-cli-registry (master @ 4c1da3a)

## Context

Two gaps motivate this feature:

1. **Health is never produced.** The `get_cli_health` op (`core/ops_registry.py`, via
   `queries.cli_health`) already reads `health_status` from the DB and is exposed over
   A2A + MCP — but **nothing ever writes a real health status**, because `probe_fleet`
   (`core/prober/prober.py`) is not called by any command. So `get_cli_health` always
   returns the seed value (`UNKNOWN`). The consumer exists; the producer is missing.

2. **The reserved prober config keys are still dead.** The v1.1 config-honesty work
   left `[thresholds.reserved_prober]` (`probe_timeout`, `max_probe_output_bytes`,
   `probe_concurrency`, `staleness_ttl`) labeled "reserved — consumed once a probe
   command lands." The original ask ("make `max_probe_output_bytes` overridable at
   runtime") cannot be satisfied as plumbing until that command exists.

This spec adds a one-shot **`probe`** command (the missing producer, which also makes
the 4 reserved keys live) and a complementary read-only **`overview`** command — a
human-readable `rich` render of the catalog (CLIs, capabilities, health, edges) that
displays the health `probe` produces.

**Intended outcome:** `probe` writes real health that `get_cli_health` and `overview`
surface; editing any of the 4 prober config keys provably changes probe behavior;
`overview` gives an at-a-glance view of the fleet; the only config section still marked
reserved is `[planner.reserved]`.

## Architecture

Three thin layers, clean producer/presenter split — no daemon, no network surface, no
scheduling:

1. **`probe_fleet` config-passthrough** (`core/prober/prober.py`) — extend the existing
   function to forward `timeout` + `max_output_bytes` into each `probe_one` call and to
   accept `staleness_ttl` instead of the module constant. All new params default to
   today's values → backward-compatible.
2. **`probe` command** (`core/cli/main.py`) — one-shot; mirrors the `populate` command's
   shape; reads the 4 prober values from config and calls `probe_fleet`.
3. **`overview` command + renderer** (`core/cli/main.py` + new `core/tui/overview.py`) —
   read-only; calls existing catalog queries (no new SQL) and renders with `rich`.

**New runtime dependency:** `rich` (explicitly approved by the user). Isolated to the
single `core/tui/` presentation module so the rest of the codebase stays `rich`-free.

---

## Component 1 — `probe` command

**Invocation:** `a2a-cli-registry probe [--db registry.db] [--config <path>]`
No per-run flags — config is the single tuning surface (matches `mass_removal`).

**Behavior:**
1. Load config → `init_db(args.db)` → open a session.
2. Resolve 4 values from `[thresholds.reserved_prober]` (renamed live; see Component 4),
   each falling back to its code default when the section/key is absent:
   | Key | Default |
   |---|---|
   | `probe_timeout` | `10.0` |
   | `max_probe_output_bytes` | `65536` |
   | `probe_concurrency` | `8` |
   | `staleness_ttl` | `3600` |
3. Call `probe_fleet(session, [PythonAdapter()], _RealClock(), concurrency=…,
   probe_timeout=…, max_output_bytes=…, staleness_ttl=…)`.
4. `print(json.dumps(summary))` (the counts dict `probe_fleet` already returns:
   `probed/healthy/unhealthy/stale/unknown`), return 0.

**`probe_fleet` signature change (backward-compatible):**
```python
def probe_fleet(session, adapters, clock, concurrency=8,
                probe_timeout=10.0, max_output_bytes=_DEFAULT_MAX_OUTPUT_BYTES,
                staleness_ttl=_STALE_TTL_SECONDS) -> dict:
```
- `pool.submit(probe_one, cmd)` → `pool.submit(probe_one, cmd, probe_timeout, max_output_bytes)`
  so the config-tuned timeout + output cap actually reach each probe.
- The hardcoded `_STALE_TTL_SECONDS` comparison uses the `staleness_ttl` param.
- `_STALE_TTL_SECONDS` / `_DEFAULT_MAX_OUTPUT_BYTES` remain as the default constants.

**Safety:** `probe` is the second sanctioned CLI-spawn site (after the prober internals).
It executes adapter `health_cmd`s under the prober's existing isolation (timeout +
SIGKILL + bounded output drain) — exactly what these config keys tune. Local operator
command; no network/auth surface added.

---

## Component 2 — `overview` command

**Invocation:** `a2a-cli-registry overview [--db registry.db] [--query <substr>]`
No config needed (pure read). `--query` reuses `search_clis`' existing substring filter.

**Behavior:**
1. `init_db(args.db)` → open a session.
2. Read from **existing** queries only (no new SQL):
   - `search_clis(session, query)` → slug, lang, description, health_status
   - `describe_cli(session, slug)` per CLI → `capabilities` (intent_tags, input_types,
     output_types, side_effect, confidence)
   - `cli_graph(session)` → computed edges (`from`, `to`, `via_type`)
3. Assemble plain-data structures, hand to `render_overview` (Component 3), exit 0.

**Renders three sections:**
- **CLIs table** — slug, lang, health (color badge: healthy=green / unhealthy=red /
  stale=yellow / unknown=dim), short description.
- **Capabilities** (per CLI) — intent tags, input→output types, side-effect, and
  confidence (`declared` vs `inferred` styled distinctly — that distinction is
  load-bearing in this project).
- **Call-graph edges** — `from → to (via type)`, or "no edges" when empty.

Empty catalog → a clean "registry is empty" message, not a crash (consistent with how
`graph` behaves on an empty DB).

---

## Component 3 — `core/tui/overview.py` (renderer)

```python
def render_overview(clis: list[dict], graph: list[dict], *, console=None) -> None:
    """Render the catalog overview with rich. `console` defaults to a real
    rich.Console; tests pass Console(record=True) and assert on export_text()."""
```

- Takes plain dicts (exactly what the queries return) + an injectable `Console` — **no DB
  dependency**, unit-testable on pure data.
- `console` defaults to a real `rich.Console()`; the `main.py` `overview` branch does the
  DB reads and calls this.
- `rich` is imported **only** in this module — the new dependency stays isolated.

**Why a separate module:** keeps the new dep contained, and makes the renderer swappable
and independently testable from the CLI wiring.

---

## Component 4 — Config promotion (reserved → live)

The 4 prober keys move out of "reserved": rename `[thresholds.reserved_prober]` →
`[probe]` (a live section), holding `probe_timeout`, `max_probe_output_bytes`,
`probe_concurrency`, `staleness_ttl`. After this change:
- `[probe]` and `[thresholds].mass_removal` and `[vocabulary].*` and `cli_audit_path`
  are **live**.
- Only `[planner.reserved]` remains reserved.

Update accordingly: the config file's header comment + inline markers, the
`test_reference_config_*` guard tests in `tests/test_cli.py`, and the README
"Configuration" table.

**Decision (binding):** use a new `[probe]` live table for the 4 keys (not nested under
`[thresholds]`) — it reads clearly and groups the prober knobs by purpose. The `probe`
reader, config file, guard tests, and README all use the `[probe]` path. (`mass_removal`
stays under `[thresholds]` — it is a populate guard, not a probe knob.)

---

## Error Handling

- **`probe`:** per-CLI probe failure is already isolated inside `probe_fleet` (per-future
  `try/except` → that CLI marked unhealthy, fleet continues). Bad/missing `--config`
  propagates like `populate` today (fail-closed, no silent empty run).
- **`overview`:** missing DB → `init_db` creates an empty one → "registry is empty"
  render. No crash on empty catalog or empty graph.
- No bare `except Exception`; no new file writes (no atomic-write concern); `rich` import
  confined to `core/tui/overview.py`.

## Testing

- **`probe_fleet`:** new tests prove `probe_timeout`/`max_output_bytes` reach `probe_one`
  (spy on `probe_one` capturing args) and `staleness_ttl` drives the STALE cutoff;
  **existing** `probe_fleet` tests pass unchanged (backward-compat proof).
- **`probe` command:** config values flow into `probe_fleet` (spy on
  `core.cli.main.probe_fleet`, assert 4 kwargs); fallback-to-defaults when the section is
  absent; summary JSON printed + exit 0.
- **`overview` render:** `Console(record=True).export_text()` assertions — each health
  badge label, declared-vs-inferred styling, an edge line, and the empty-catalog message.
- **Config honesty:** update dead-key/live-vs-reserved guard tests — the 4 prober keys
  are now live; only `[planner.reserved]` stays reserved.
- **Packaging:** extend `tests/test_packaging.py` to confirm `rich` is a declared runtime
  dependency.

## Out of Scope (possible future follow-ups)

- Interactive/browsable TUI (event loop, keypresses, `textual`).
- Auto-probe inside `serve`; `--watch` loop / `probe_interval`.
- Per-CLI `--slug` probe filtering.
- A `plan` CLI command (already served over A2A + MCP).
- Implementing `audit` / `lifecycle`.

## Success Criteria

1. `probe` runs `probe_fleet` over the whole catalog and writes real `health_status`;
   `get_cli_health` and `overview` then surface it.
2. Editing `max_probe_output_bytes` (and the other 3 prober keys) in config provably
   changes probe behavior (test-proven) — the original ask is satisfied.
3. `overview` renders CLIs + capabilities + edges + health with `rich`.
4. The only reserved config section left is `[planner.reserved]`.
5. Full test suite green with `rich` added as a runtime dependency.

## File Structure

| File | Change |
|---|---|
| `core/prober/prober.py` | Add `probe_timeout`/`max_output_bytes`/`staleness_ttl` params to `probe_fleet`; forward to `probe_one`; use `staleness_ttl` param. |
| `core/cli/main.py` | Add `probe` and `overview` to command choices; add both command branches. |
| `core/tui/__init__.py`, `core/tui/overview.py` | New module: `render_overview(clis, graph, *, console=None)`. |
| `examples/reference-fleet/config.toml` | Promote 4 prober keys reserved→live (`[probe]`); update comments. |
| `pyproject.toml` | Add `rich` to `[project] dependencies`. |
| `tests/test_prober.py` | `probe_fleet` passthrough + staleness tests. |
| `tests/test_cli.py` | `probe` config-flow + `overview` smoke; update config-honesty guards. |
| `tests/test_tui.py` (new) | `render_overview` text-assertion tests. |
| `tests/test_packaging.py` | Assert `rich` declared. |
| `README.md` | Document `probe`/`overview`; update Configuration table (4 keys now live). |
