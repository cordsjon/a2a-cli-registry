# `probe` + `overview` Commands — Design

**Date:** 2026-06-22
**Status:** Revised after architecture/AI/test panel + Codex review — ready for implementation plan
**Repo:** a2a-cli-registry (master @ 4c1da3a)

> **Revision note (post-review):** A 4-reviewer panel (architecture, AI-integration,
> test/verifiability, Codex) flagged six substantive gaps in the first draft. This
> version incorporates the resolutions: per-hop health annotation in the planner
> (Component 5), an `enabled`-gated probe trust boundary (Component 1 Safety), a
> SQLite cross-process concurrency policy (Error Handling), the `render_overview`
> capabilities data-flow fix (Component 3), a health-state semantics + casing-normalization
> contract (Component 6), and tightened/ falsifiable test criteria (Testing).

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
2. Resolve 4 values from the live `[probe]` table (see Component 4 — these keys are
   promoted out of the old `[thresholds.reserved_prober]` reserved section), each falling
   back to its code default when the section/key is absent:
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
- `pool.submit(probe_one, cmd)` → `pool.submit(probe_one, cmd, probe_timeout, max_output_bytes)`.
  Positional mapping is correct against `probe_one(cmd, timeout, max_output_bytes)`
  (`core/prober/prober.py:39`). Config→param name mapping: config `probe_timeout` →
  `probe_one(timeout=)`; config `max_probe_output_bytes` → `probe_one(max_output_bytes=)`
  (the name difference across the config/code boundary is intentional — do not "fix" it).
- Replace `_STALE_TTL_SECONDS` **at the `no_cmd` staleness comparison specifically**
  (`(now - checked) > _STALE_TTL_SECONDS`, prober.py:178) with the `staleness_ttl`
  parameter. The constant remains only as the param's default value.
- **`enabled` filter:** `probe_fleet` skips CLIs where `enabled is False` (trust gate
  above) — add to the `select(Cli)` query or the partition loop; disabled CLIs are not
  spawned and not counted as probed.
- `_STALE_TTL_SECONDS` / `_DEFAULT_MAX_OUTPUT_BYTES` remain as the default constants.
- New params are trailing with defaults → existing `probe_fleet(db, [adapter], clock)`
  test calls (`tests/test_prober.py:127,143,164,178`) stay green (panel + Codex confirm).

**Safety / trust boundary (panel finding #3, Codex Critical):** `probe` is the second
sanctioned CLI-spawn site and it *executes* each CLI's `health_cmd` (e.g. `PythonAdapter`
runs `python -m <slug> --help`, which executes module code). Isolation (timeout + SIGKILL
+ bounded output drain) bounds *resource* blast radius but is **not authorization**. The
trust decision for v1:
- **Probe only CLIs where `Cli.enabled is True`** (the existing per-CLI kill switch,
  `core/models.py:17`). `probe_fleet` must add this filter to its `select(Cli)` /
  iteration — a disabled CLI is never spawned.
- **Execute regardless of `declared` vs `inferred` confidence.** Rationale (recorded
  decision): `probe` runs LOCAL CLIs the operator themselves populated into their own
  registry from their own `cli-audit` export — the operator already trusts these binaries
  exist and are runnable on their machine. Inference in this project is about
  *capabilities* (what a CLI does), not about whether the binary is safe to `--help`. So
  the fail-UNSAFE posture (which governs *planning through* unverified side-effects)
  does not extend to refusing to health-check an operator-installed binary. `enabled` is
  the operator's opt-out.
- **Document this contract** in the README/SECURITY so the trust assumption is explicit:
  probe trusts populated+enabled entries; isolation bounds blast radius; disable a CLI to
  exclude it from probing.

Local operator command; no network/auth surface added.

---

## Component 2 — `overview` command

**Invocation:** `a2a-cli-registry overview [--db registry.db] [--query <substr>]`
No config needed (pure read). `--query` reuses `search_clis`' existing substring filter.

**Behavior:**
1. `init_db(args.db)` → open a session.
2. Read from **existing** queries only (no new SQL):
   - `search_clis(session, query)` → slug, lang, description, health_status (NO caps)
   - `describe_cli(session, slug)` per matching CLI → its `capabilities` (intent_tags,
     input_types, output_types, side_effect, confidence)
   - `cli_graph(session)` → computed edges (`from`, `to`, `via_type`)
3. **Assemble an ENRICHED cli list** (panel finding #1 — `search_clis` rows lack
   capabilities; the renderer needs them): for each row from `search_clis`, attach its
   caps, e.g. `row["capabilities"] = describe_cli(session, row["slug"])["capabilities"]`.
   The enriched list (slug/lang/description/health_status/capabilities) is what
   `render_overview` receives — so the renderer needs no DB access and the 2-arg
   `(clis, graph)` signature is honest. (This is an N+1 read over the matched set; for a
   local single-connection SQLite registry with small N this is an accepted trade — noted,
   not optimized. If N grows, add a `caps_by_slug(session)` helper later.)
4. Hand the enriched list + edges to `render_overview` (Component 3), exit 0.

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
    """Render the catalog overview with rich. `clis` are ENRICHED rows
    (slug/lang/description/health_status/capabilities — see Component 2 step 3).
    `console` defaults to a real rich.Console; tests pass
    Console(record=True, width=120) and assert on export_text()."""
```

- Takes enriched plain dicts (Component 2 step 3) + an injectable `Console` — **no DB
  dependency**, unit-testable on pure data.
- `console` defaults to a real `rich.Console()`; the `main.py` `overview` branch does the
  DB reads + enrichment and calls this.
- `rich` is imported **only** in this module — the new dependency stays isolated. An
  import-isolation guard test (Testing) asserts no module outside `core/tui/` imports
  `rich`, so isolation is enforced, not just convention.

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

## Component 5 — Planner health annotation (panel finding #2, Codex #3)

probe writes `health_status`, but `plan_cli_chain` ranks only on
(length, side_effect_count, min_confidence_rank) and never reads health — so a chain
through a just-marked-`unhealthy` CLI would still be returned and top-ranked. For an
agent-first registry, that leaves probe's value half-realized.

**Decision (recorded): annotate per-hop, do NOT change ranking (MVA).**
- `_finalize` in `core/planner/search.py:122-133` already builds per-hop dicts
  (`hop = {"slug", "side_effect", "provenance"}`). Add the hop CLI's `health_status` to
  each hop dict.
- `queries.plan_cli_chain` (`core/catalog/queries.py:47-50`) already emits `hops` in its
  output — so the health then flows out over A2A + MCP automatically, no op-registry change.
- **Ranking semantics are unchanged.** Health is surfaced for the agent to decide; no
  chain is hidden or reordered by health in this spec.
- This is the MVA that makes probe's output agent-*actionable* (not just visible via
  `get_cli_health`). Health-aware *ranking/exclusion* is an explicit follow-up, out of
  scope here.

**Note:** the planner reads capabilities, not `Cli` rows, today. Threading
`health_status` into hops requires the planner (or `_finalize`) to have each hop slug's
health available. Confirm the cleanest source during implementation — either the planner
looks up `Cli.health_status` per hop slug, or `queries.plan_cli_chain` enriches the hops
after `_plan` returns (preferred: keep `search.py` DB-light, enrich in `queries.py`).

---

## Component 6 — Health-state semantics + casing normalization (panel finding #5)

**Casing bug (pre-existing, this spec surfaces + fixes it):** `prober.py` writes lowercase
`"healthy"`/`"unhealthy"` (lines 87,169) but UPPERCASE `"STALE"`/`"UNKNOWN"` (lines
179,183), and `queries.cli_health` returns `"UNKNOWN"` (line 37). An agent string-matching
on health — and the `overview` badge map — must handle both cases or silently fall through.
**Fix:** normalize all health-status values to a single case. Use lowercase
(`healthy/unhealthy/stale/unknown`) consistently in `prober.py` and `queries.py`; the
`overview` badge map and any agent-facing comparison then key off one canonical form.
Update the counts dict keys + any test asserting the old uppercase strings.

**State semantics (agent contract — add to README/SECURITY):**
| State | Meaning | Recommended agent action |
|---|---|---|
| `healthy` | probed, exit 0 | safe to use |
| `unhealthy` | probed, non-zero exit / timeout / spawn error | avoid / treat as broken |
| `stale` | *unprobeable* CLI (no adapter/health_cmd) last touched > `staleness_ttl` ago | treat as unknown; do not assume healthy |
| `unknown` | never probed, or unprobeable and within TTL | no signal; do not infer healthy |

> Semantic trap to document: `stale`/`unknown` apply ONLY to *unprobeable* CLIs (no
> `health_cmd`). A CLI that *was* probed is always `healthy`/`unhealthy`, never `stale`.
> So `stale` here means "we can't probe this and last saw it a while ago," NOT "healthy
> but re-check." The README state table must say this so neither agents nor humans
> misread the yellow badge.

**`staleness_ttl` blast radius:** unlike the other 3 probe knobs (which only affect *how*
probing runs), `staleness_ttl` changes *agent-visible* health output (which unprobeable
CLIs read `stale` vs `unknown` via `get_cli_health`/`search_cli_catalog`). The config docs
should flag that this one key tunes what agents perceive, not just probe internals.

---

## Error Handling

- **`probe`:** per-CLI probe failure is already isolated inside `probe_fleet` (per-future
  `try/except` → that CLI marked unhealthy, fleet continues). Bad/missing `--config`
  propagates like `populate` today (fail-closed, no silent empty run). Empty catalog →
  returns the zero-count summary `{"probed":0,...}`, exit 0 (no crash).
- **`overview`:** missing DB → `init_db` creates an empty one → "registry is empty"
  render. No crash on empty catalog or empty graph.
- **Cross-process SQLite write contention (panel finding #4, Codex #4 — corrects a false
  claim in the first draft):** `probe` *does write* — `probe_fleet` calls
  `session.commit()` updating `health_status`/`health_checked_at` on every probed Cli row.
  `init_db`'s StaticPool single-connection guarantee protects threads *within one
  process*; `probe` runs as a *separate process* from `serve`. So `probe` writing while
  `serve` reads the same SQLite file can raise `SQLITE_BUSY` ("database is locked").
  **Policy:** wrap the `probe` command's mutation in the existing, currently-unused
  `with_file_lock(args.db)` helper (`core/store/db.py:43`) AND set a busy timeout on the
  engine (`connect_args={"timeout": <n>}`) so a brief read-lock from `serve` doesn't fail
  the probe. Document that `probe` and `serve` may run concurrently and the lock+timeout
  is what makes that safe. (Enabling SQLite WAL mode is a stronger option but is a broader
  `init_db` change affecting all commands — note it as a follow-up, don't pull it in here.)
- No bare `except Exception`; `rich` import confined to `core/tui/overview.py`.

Tests must FALSIFY behavior, not just plumbing (panel test-reviewer findings):

- **`probe_fleet` params (behavioral, not spy-only):**
  - `staleness_ttl`: pass a **custom** TTL (e.g. 60s) and a CLI stale under it but NOT
    under `_STALE_TTL_SECONDS`; assert it's marked `stale`. Then assert the same CLI is
    NOT stale under the default. (A spy can't catch a hardcoded-constant bug; a custom TTL
    can.)
  - `max_output_bytes`: drive a runaway-output health_cmd through the **fleet** layer with
    a small `max_output_bytes` and assert it completes without hanging (behavioral cap,
    mirroring `test_probe_one_caps_runaway_output` but at fleet level) — not merely that
    the kwarg was forwarded.
  - `probe_concurrency`: assert it sets `ThreadPoolExecutor(max_workers=...)` to the
    configured value (this live key has NO test in the first draft).
  - `enabled` gate: a CLI with `enabled=False` is NOT spawned (spy on probe_one / assert
    not in counts).
  - **Existing** `probe_fleet` tests (`tests/test_prober.py:127,143,164,178`) pass
    unchanged — backward-compat proof.
- **`probe` command:** config values flow into `probe_fleet` (spy on
  `core.cli.main.probe_fleet`, assert all 4 kwargs); **a single test covering all 4
  fallback defaults** when `[probe]` is absent (mirror `test_mass_removal_falls_back...`);
  summary JSON printed + exit 0; empty-catalog → zero-count summary + exit 0.
- **End-to-end producer→consumer (success criterion #1, was untested):** populate a CLI
  (health UNKNOWN) → run `probe` via `main([...])` (probe_fleet may be stubbed to set a
  known status) → call `get_cli_health` and assert it returns the updated status. Proves
  the produce→consume link, not just each half in isolation.
- **Planner annotation (Component 5):** a planned chain's hop dicts include
  `health_status` for each hop slug.
- **`overview` render:** use `Console(record=True, width=120)` (pin width so layout is
  deterministic) and assert on `export_text()` for: each health label string present;
  the words "declared"/"inferred" present (assert on the DATA→text mapping, NOT on ANSI
  styling, which `export_text()` strips); an edge line; the `--query` filter excludes a
  non-matching CLI; the empty-catalog message.
- **Config honesty (Component 4):** the 4 prober keys are now live under `[probe]`; the
  guard tests must (a) assert `[thresholds.reserved_prober]` is GONE (rename happened),
  (b) assert `[planner.reserved]` is still present, (c) keep the no-dead-keys guard green.
- **Casing normalization (Component 6):** assert all health states are lowercase across
  `prober.py` outputs and `queries.cli_health`; update any test asserting old uppercase
  `STALE`/`UNKNOWN`.
- **Dependency isolation:** a guard test asserting no module outside `core/tui/` imports
  `rich` (grep/AST over `core/`).
- **Packaging:** extend `tests/test_packaging.py` to confirm `rich` is a declared runtime
  dependency.
- **Probe test determinism:** probe tests monkeypatch `probe_one` (or use the existing
  `spawn_spy`/trivial-cmd patterns) rather than spawning arbitrary real processes —
  fast, deterministic, environment-independent.

## Out of Scope (possible future follow-ups)

- **Health-aware planner ranking/exclusion** — Component 5 only *annotates* health per
  hop; demoting or excluding unhealthy chains is deferred.
- SQLite WAL mode in `init_db` (broader change; `probe` uses file-lock + busy-timeout instead).
- Interactive/browsable TUI (event loop, keypresses, `textual`).
- Auto-probe inside `serve`; `--watch` loop / `probe_interval`.
- Per-CLI `--slug` probe filtering.
- A `plan` CLI command (already served over A2A + MCP).
- Implementing `audit` / `lifecycle`.

## Success Criteria

1. After `probe` runs, calling `get_cli_health` for a probed CLI returns its real status
   (not `UNKNOWN`) — proven by an end-to-end produce→consume test, not each half alone.
2. The 4 probe config keys provably change behavior (not just plumbing): custom
   `staleness_ttl` flips a CLI to `stale`; small `max_output_bytes` caps a runaway fleet
   probe without hanging; `probe_concurrency` sets the pool's `max_workers`; absent
   `[probe]` falls back to all 4 defaults — each test-proven. (The original
   `max_probe_output_bytes` override ask is satisfied behaviorally.)
3. Planned chains carry per-hop `health_status` (Component 5) — visible to agents over
   A2A/MCP via the existing `hops` output.
4. `probe` skips `enabled=False` CLIs (never spawns them) — trust gate test-proven.
5. `overview` renders enriched CLIs + capabilities + edges + health; `--query` filters;
   empty catalog renders cleanly — all via `Console(record=True, width=120)` text assertions.
6. Health states are a single canonical case across `prober.py` + `queries.py`; `probe`
   and `serve` can run concurrently without `SQLITE_BUSY` (file-lock + busy-timeout).
7. Config: 4 prober keys live under `[probe]`; only `[planner.reserved]` stays reserved
   (guard tests assert both). `rich` declared as a runtime dep AND confined to `core/tui/`
   (isolation guard test). Version bumped to `1.1.0` with changelog note.

## File Structure

| File | Change |
|---|---|
| `core/prober/prober.py` | Add `probe_timeout`/`max_output_bytes`/`staleness_ttl` params to `probe_fleet`; forward to `probe_one`; use `staleness_ttl` param at the staleness comparison; add `enabled` filter; **normalize all health states to lowercase** (Component 6). |
| `core/cli/main.py` | Add `probe`/`overview` to command choices + branches; `_probe_config(cfg)` reader (one helper, 4 keys + defaults — mirrors `_mass_removal_threshold`); `probe` wraps mutation in `with_file_lock`. |
| `core/planner/search.py` and/or `core/catalog/queries.py` | Annotate each plan hop with `health_status` (Component 5 — prefer enriching in `queries.plan_cli_chain` to keep `search.py` DB-light). |
| `core/catalog/queries.py` | Lowercase the `cli_health` `UNKNOWN` fallback (Component 6). |
| `core/store/db.py` | Add busy-timeout to `init_db` engine `connect_args` (Component / Error-Handling concurrency policy). |
| `core/tui/__init__.py`, `core/tui/overview.py` | New module: `render_overview(clis, graph, *, console=None)` (clis = enriched rows). |
| `examples/reference-fleet/config.toml` | Promote 4 prober keys reserved→live under `[probe]`; remove `[thresholds.reserved_prober]`; update comments. |
| `pyproject.toml` | Add `rich` to `[project] dependencies`; bump version → `1.1.0`. |
| `CHANGELOG.md` | Note probe/overview, `rich` dep, health states, config promotion. |
| `tests/test_prober.py` | `probe_fleet` behavioral tests (custom-TTL staleness, fleet output-cap, concurrency, enabled gate); casing assertions; existing tests stay green. |
| `tests/test_cli.py` | `probe` config-flow + all-4-defaults + empty-catalog; e2e produce→consume; `overview` render/`--query`/empty; updated config-honesty guards (`[probe]` live, `[thresholds.reserved_prober]` gone, `[planner.reserved]` present). |
| `tests/test_tui.py` (new) | `render_overview` text-assertion tests (`width=120`, data→text not ANSI). |
| `tests/test_planner.py` | Hop dicts include `health_status`. |
| `tests/test_packaging.py` | Assert `rich` declared; import-isolation guard (no `rich` outside `core/tui/`). |
| `README.md`, `SECURITY.md` | Document `probe`/`overview`; health-state semantics table + agent contract; probe trust boundary (`enabled` gate); Configuration table (4 keys now live). |
